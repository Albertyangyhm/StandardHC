import pickle
import numpy as np
import torch
from scipy.special import logsumexp


def get_delta_LR(pL, pR):
    """
    Calculate invariant mass of a node, given its child momenta
    """
    pP = pR + pL

    """Parent invariant mass squared"""
    tp1 = pP[0] ** 2 - np.linalg.norm(pP[1::]) ** 2

    return tp1

#
# def get_delta_PC(p, pC):
#     """
#     Calculate delta of an edge, given its momentum and the momentum of a child
#     """
#     return np.sqrt(np.sum((p / 2 - pC) ** 2))



def split_logLH(pL, tL, pR, tR, t_cut, lam):
    """
    Take two nodes and return the splitting log likelihood
    """
    pP = pR + pL

    """Parent invariant mass squared"""
    tp1 = pP[0] ** 2 - np.linalg.norm(pP[1::]) ** 2

    tmax = max(tL,tR)
    tmin = min(tL,tR)

    tp2 = (np.sqrt(tp1) - np.sqrt(tmax)) ** 2

    """ We add a normalization factor -np.log(1 - np.exp(- lam)) because we need the mass squared to be strictly decreasing """
    def get_p(tP, t, t_cut, lam):
        if t > 0:
            return -np.log(1 - np.exp(- lam)) + np.log(lam) - np.log(tP) - lam * t / tP

        else: # if t<t_min then we set t=0
            return -np.log(1 - np.exp(- lam)) + np.log(1 - np.exp(-lam * t_cut / tP))

    """We sample a unit vector uniformly over the 2-sphere, so the angular likelihood is 1/(4*pi)"""
    logLH = (
        get_p(tp1, tmax, t_cut, lam)
        + get_p(tp2, tmin, t_cut, lam)
        + np.log(1 / (4 * np.pi))
    )

    "If the pairing is not allowed"
    if tp1 < t_cut:
        logLH = - np.inf

    return logLH




def fill_jet_info(jet, parent_id=None):
    """
    Fill jet["deltas"] amd jet["draws"] given jet["tree"] and jet["content"]
    Assing r = None to the root and the leaves, and assign delta = 0 to the leaves
    """
    deltas = []
    draws = []

    root_id = jet["root_id"]

    _get_jet_info(jet, root_id=root_id, parent_id=parent_id, deltas=deltas, draws=draws)

    jet["deltas"] = deltas
    jet["draws"] = draws

    return jet

def _get_jet_info(jet, root_id=None, parent_id=None, deltas=None, draws=None):
    """
    Recursion to fill jet["deltas"] amd jet["draws"]
    """

    if jet["tree"][root_id][0] != -1 and jet["tree"][root_id][1] != -1:

        idL = jet["tree"][root_id][0]
        idR = jet["tree"][root_id][1]
        pL = jet["content"][idL]
        pR = jet["content"][idR]
        delta = get_delta_LR(pL, pR)
        if parent_id is not None:
            # print("Parent id = ", parent_id)
            # print("Len deltas = ",len(deltas))
            # pP = jet["content"][parent_id]
            # delta_parent2 = pP[0] ** 2 - np.linalg.norm(pP[1::]) ** 2
            delta_parent = deltas[parent_id]
            # print("DP 1 = ",delta_parent)
            # print("DP 2 = ", delta_parent2)
            r = torch.tensor(delta / delta_parent)
        else:
            r = None

        deltas.append(delta)
        draws.append(r)

        _get_jet_info(jet, root_id=idL, parent_id=root_id, deltas=deltas, draws=draws)
        _get_jet_info(jet, root_id=idR, parent_id=root_id, deltas=deltas, draws=draws)

    else:
        if jet["tree"][root_id][0] * jet["tree"][root_id][1] != 1:
            raise ValueError(f"Invalid jet left and right child are not both -1")
        else:
            deltas.append(0)
            draws.append(None)


def enrich_jet_logLH(jet, delta_min=None, dij=False, alpha = None):
    """
    Attach splitting log likelihood to each edge, by calling recursive
    _get_jet_likelihood.
    """
    logLH = []
    dijList = []

    root_id = jet["root_id"]

    if delta_min is None:
        delta_min = jet.get("pt_cut")
        if delta_min is None:
            raise ValueError(f"No pt_cut specified by the jet.")

    _get_jet_logLH(
        jet,
        root_id = root_id,
        delta_min = delta_min,
        logLH = logLH,
        dij = dij,
        dijList = dijList,
        alpha = alpha,
    )

    jet["logLH"] = np.asarray(logLH)
    jet["dij"] = dijList
    return jet


def _get_jet_logLH(
        jet,
        root_id = None,
        delta_min = None,
        logLH = None,
        dij = False,
        dijList = None,
        alpha = None
):
    """
    Recursively enrich every edge from root_id downward with their log likelihood.
    log likelihood of a leaf is 0. Assumes a valid jet.
    """
    if jet["tree"][root_id][0] != -1:


        idL = jet["tree"][root_id][0]
        idR = jet["tree"][root_id][1]
        pL = jet["content"][idL]
        pR = jet["content"][idR]
        tL = jet["deltas"][idL]
        tR = jet["deltas"][idR]

        Lambda = jet["Lambda"]
        if root_id == jet["root_id"]:
            Lambda = jet["LambdaRoot"]


        # llh = split_logLH(pL, tL, pR, tR, delta_min, Lambda)
        llh = split_logLH_with_stop_nonstop_prob(pL, pR, delta_min, Lambda)
        logLH.append(llh)
        # print('logLH = ', llh)

        if dij:

            """ dij=min(pTi^(2 alpha),pTj^(2 alpha)) * [arccos((pi.pj)/|pi|*|pj|)]^2 """
            dijs= [float(llh)]

            for alpha in [-1,0,1]:

                tempCos = np.dot(pL[1::], pR[1::]) / (np.linalg.norm(pL[1::]) * np.linalg.norm(pR[1::]))
                if abs(tempCos) > 1: tempCos = np.sign(tempCos)

                dijVal = np.sort((np.array([np.linalg.norm(pL[1:3]),np.linalg.norm(pR[1:3])])) ** (2 * alpha))[0]  * \
                         (
                             np.arccos(tempCos)
                          ) ** 2

                dijs.append(dijVal)

            dijList.append(dijs)


        _get_jet_logLH(
            jet,
            root_id = idL,
            delta_min = delta_min,
            logLH = logLH,
            dij = dij,
            dijList = dijList,
            alpha = alpha,
        )
        _get_jet_logLH(
            jet,
            root_id = idR,
            delta_min = delta_min,
            logLH = logLH,
            dij = dij,
            dijList = dijList,
            alpha = alpha,
        )

    else:

        logLH.append(0)



def split_logLH_with_stop_nonstop_prob(pL, pR, t_cut, lam):
    """
    Take two nodes and return the splitting log likelihood
    """
    tL = pL[0] ** 2 - np.linalg.norm(pL[1::]) ** 2
    tR = pR[0] ** 2 - np.linalg.norm(pR[1::]) ** 2


    pP = pR + pL


    """Parent invariant mass squared"""
    tp = pP[0] ** 2 - np.linalg.norm(pP[1::]) ** 2

    if tp<=0 or tL<0 or tR<0:
        return - np.inf

    # print("tP = ", tp, " tL = ", tL, " | tR= ", tR)
    # print("lam= ",lam, " | pP = ", pP, " pL = ", pL, " | pR= ", pR)

    """ We add a normalization factor -np.log(1 - np.exp(- lam)) because we need the mass squared to be strictly decreasing. This way the likelihood integrates to 1 for 0<t<t_p. All leaves should have t=0, this is a convention we are taking (instead of keeping their value for t given that it is below the threshold t_cut)"""
    def get_logp(tP_local, t, t_cut, lam):


        if t > t_cut:
            """ Probability of the shower to stop F_s"""
            # F_s = 1 / (1 - np.exp(- lam)) * (1 - np.exp(-lam * t_cut / tP_local))
            # if F_s>=1:
            #     print("Fs = ", F_s, "| tP_local = ", tP_local, "| t_cut = ", t_cut, "| t = ",t)

            # print("Inner - t = ",t," | tL =",tL, " | tR = ",tR," pL = ", pL, " | pR= ", pR, " | pP = ", pP, "logLH = ",-np.log(1 - np.exp(- lam)) + np.log(lam) - np.log(tP_local) - lam * t / tP_local)
            # return -np.log(1 - np.exp(- lam)) + np.log(lam) - np.log(tP_local) - lam * t / tP_local + np.log(1-F_s)
            return -np.log(1 - np.exp(- (1. - 1e-3)*lam)) + np.log(lam) - np.log(tP_local) - lam * t / tP_local

        else: # For leaves we have t<t_cut
            t_upper = min(tP_local,t_cut) #There are cases where tp2 < t_cut
            log_F_s = -np.log(1 - np.exp(- (1. - 1e-3)*lam)) + np.log(1 - np.exp(-lam * t_upper / tP_local))
            # print("Outer - t = ",t," | tL =",tL, " | tR = ",tR," pL = ", pL, " | pR= ", pR, " | pP = ", pP, "logLH = ", log_F_s)
            return log_F_s


    if tp <= t_cut:
        "If the pairing is not allowed"
        logLH = - np.inf

    elif tL >=(1 - 1e-3)* tp or tR >=(1 - 1e-3)* tp:
        # print("The pairing is not allowed because tL or tR are greater than tP")
        logLH = - np.inf

    elif np.sqrt(tL) + np.sqrt(tR) > np.sqrt(tp):
        print("Breaking invariant mass inequality condition")
        logLH = - np.inf


    else:
        """We sample a unit vector uniformly over the 2-sphere, so the angular likelihood is 1/(4*pi)"""

        tpLR = (np.sqrt(tp) - np.sqrt(tL)) ** 2
        tpRL = (np.sqrt(tp) - np.sqrt(tR)) ** 2

        logpLR = np.log(1/2)+ get_logp(tp, tL, t_cut, lam) + get_logp(tpLR, tR, t_cut, lam) #First sample tL
        logpRL = np.log(1/2)+ get_logp(tp, tR, t_cut, lam) + get_logp(tpRL, tL, t_cut, lam) #First sample tR

        logp_split = logsumexp(np.asarray([logpLR, logpRL]))

        logLH = (logp_split + np.log(1 / (4 * np.pi)) )

    return logLH
