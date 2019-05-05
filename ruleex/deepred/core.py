from threading import Thread

from ruleex.tree.rule import AxisRule
from ruleex.tree.ruletree import RuleTree
from sklearn import tree
import time

from ruleex.tree.utils import sklearndt_to_ruletree
import numpy as np

ONE_CLASS_ON_LEAF = "one_class_on_leafs"
DEFAULT_ONE_CLASS_ON_LEAF = True
INITIAL_DT_TRAIN_PARAMS = "initial_dt_train_params"
DEFAULT_INITIAL_DT_TRAIN_PARAMS = {"max_depth": 5}
DT_TRAIN_PARAMS = "dt_train_params"
DEFAULT_DT_TRAIN_PARAMS = {"max_depth": 3}
MIN_SPLIT_FRACTION = "min_split_fraction"
DEFAULT_MIN_SPLIT_FRACTION = 0.02
MIN_RULE_SAMPLES = "min_rule_samples"
DEFAULT_MIN_RULE_SAMPLES = 1
VARBOSE = "varbose"
DEFAULT_VARBOSE = 1
OUTPUT_DIR = "output_dir"
DEFAULT_OUTPUT_DIR = "runs/"
SAVE_PROCESS = "save_process"
DEFAULT_SAVE_PROCESS = False
BUILD_FIRST = "build_first"
DEFAULT_BUILD_FIRST = True

INF = "inf"

DEFAULT_PARAMS = {
                  ONE_CLASS_ON_LEAF: DEFAULT_ONE_CLASS_ON_LEAF,
                  DT_TRAIN_PARAMS: DEFAULT_DT_TRAIN_PARAMS,
                  INITIAL_DT_TRAIN_PARAMS: DEFAULT_INITIAL_DT_TRAIN_PARAMS,
                  VARBOSE: DEFAULT_VARBOSE,
                  MIN_SPLIT_FRACTION: DEFAULT_MIN_SPLIT_FRACTION,
                  MIN_RULE_SAMPLES: DEFAULT_MIN_RULE_SAMPLES,
                  OUTPUT_DIR: DEFAULT_OUTPUT_DIR,
                  SAVE_PROCESS: DEFAULT_SAVE_PROCESS,
                  BUILD_FIRST: DEFAULT_BUILD_FIRST,
                  }


def values_2_classes(values):
    return np.argmax(values, 1)


def __merge(rt, dt, all_rt_nodes=None):
    """
    Inserts sub-trees stored in dt into the rt and returns a new RuleTree generated by this process
    :param rt: RuleTree object
    :param dt: a dictionary that maps pair (index, threshold) into the RuleTree
    :param all_rt_nodes: all_nodes of the rt
    :return: rt that have substituted nodes by RuleTrees in dt
    """
    rt.type = "deepred-ddag"
    def rulesToSubs(all_rules):
        output = list()
        for rule in all_rules:
            if type(rule) is AxisRule:
                output.append(rule)
        return output

    def mergeDT(root):
        actrt = dt[(root.i, root.b)].copy()
        all_rules = actrt.get_all_nodes()
        actrt = actrt.replace_leaf_with_set([1], root.true_branch, all_nodes=all_rules)
        actrt = actrt.replace_leaf_with_set([0], root.false_branch, all_nodes=all_rules)
        if root.true_branch:
            all_rules.add(root.true_branch)
        if root.false_branch:
            all_rules.add(root.false_branch)
        new_pred = actrt.get_predecessor_dict(all_nodes=all_rules)
        rt.replace_rule(root, actrt.root, pred_entries=pred[root])
        predEntries = pred[root]
        del pred[root]
        pred[actrt.root] = predEntries
        if root.true_branch in new_pred:
            pred[root.true_branch] = new_pred[root.true_branch]
        if root.false_branch in new_pred:
            pred[root.false_branch] = new_pred[root.false_branch]
    if not all_rt_nodes:
        all_rt_nodes = rt.get_all_nodes()
    pred = rt.get_predecessor_dict(all_rt_nodes)
    #merge
    rts = rulesToSubs(all_rt_nodes)
    for i, rule in enumerate(rts):
        if (rule.i, rule.b) in dt:
            mergeDT(rule)
    return rt


def deepred(layers_activations, params):
    """

    :param layers_activations: a list of numpy arrays,
        layers activations with input layer (X) as the first and output layer (Y) as the last
    :param params: a dictionary with all parameters, keys are defined as constants of this module,
        DT_TRAIN_PARAMS: training parameters that are passed into the sklearn.tree.DecisionTreeClassifier
        INITIAL_DT_TRAIN_PARAMS: training parameters that are passed into the sklearn.tree.DecisionTreeClassifier
            for the purpouse of the generation of the initial tree
        VARBOSE: varbose level
        MIN_SPLIT_FRACTION: minimal ration of the splited samples on the node on sub-trees
        MIN_RULE_SAMPLES: minimal train samples on the node on sub-trees
        OUTPUT_DIR: if the VARBOSE is higher than 2 then the builded tree are shown in pdf by graphviz and
            OUTPUT_DIR defines the directory where these pdf and dot files are stored
        SAVE_PROCESS: if True than all process is saved in params[INF]
            saved are copies of all generated DDAGs and sub-trees
        BUILD_FIRST: if True then the initial DT is build by sklearn otherwise the RuleTree.halftree is used

    :return: ruletree as extracted ddag
        in dictionary params under key INF following informations:
            inf["dag_size"]: list of the dag size while training
            inf["size_befor_reduc"]: list of ddag size before reduction
            inf["fidelity"]: fidelity for each step
            inf["sub_tree_size"]: list of all sizes of subtituing trees
            inf["sub_tree_acc"]: their accuracies
        if SAVE_PROCESS is enebled then also contain
            inf["dag"]: dags for each step of alg
            inf["sub_tree"]: dictionary of subtituing trees for each step
    """

    # function definitions

    def getXforLayer(actLyer):
        return layers_activations[actLyer]

    def getY(actLayer, i, th):
        return (layers_activations[actLayer + 1][:, i] > th)

    class DTBuilder(Thread):
        def __init__(self, index, i, th):
            Thread.__init__(self)
            self.index = index
            self.i = i
            self.th = th

        def run(self):
            tic1 = time.time()
            if params[VARBOSE] > 1:
                print("[deepred]: Start processing decision tree for {} < x_{} ({}\{})".format(
                    self.th,
                    self.i,
                    self.index+1,
                    len(threshold)
                ))
            dt_base = tree.DecisionTreeClassifier(**params[DT_TRAIN_PARAMS])
            x = getXforLayer(actLayer)  # [indexes[(i, th)]]
            y = getY(actLayer, self.i, self.th)  # [indexes[(i, th)]]

            buld_tree= sklearndt_to_ruletree(
                dt_base.fit(x, y),
                params[ONE_CLASS_ON_LEAF],
                min_rule_samples=params[MIN_RULE_SAMPLES],
                min_split_fraction=params[MIN_SPLIT_FRACTION])
            dt[(self.i, self.th)] = buld_tree
            if params[SAVE_PROCESS]:
                inf["sub_tree"][-1][(self.i, self.th)] = buld_tree.copy()
            a = buld_tree.eval_all(x)
            accuracy = np.sum(a == y) / len(a)
            inf["sub_tree_acc"][-1][self.index] = accuracy
            inf["sub_tree_size"][-1][self.index] = len(buld_tree.get_all_nodes())
            inf["sub_tree_time"][-1][self.index] = time.time() - tic1
            if params[VARBOSE] > 1:
                print("[deepred]: End processing decision tree for {} < x_{} ({}\{}) -- accuracy: {}".format(
                    self.th,
                    self.i,
                    self.index+1,
                    len(threshold),
                    accuracy
                ))
    # the algorithm
    params = dict(DEFAULT_PARAMS, **params)
    lastLayerIndex = len(layers_activations) - 1
    dt_base = tree.DecisionTreeClassifier(**params[INITIAL_DT_TRAIN_PARAMS])
    if params[BUILD_FIRST]:
        dt = dt_base.fit(getXforLayer(lastLayerIndex - 1), values_2_classes(getXforLayer(lastLayerIndex)))
        rt = sklearndt_to_ruletree(
            dt,
            params[ONE_CLASS_ON_LEAF],
            min_rule_samples=params[MIN_RULE_SAMPLES],
            min_split_fraction=params[MIN_SPLIT_FRACTION])
    else:
        rt = RuleTree.half_in_ruletree(len(layers_activations[-1][0]))
    all_nodes = rt.get_all_nodes()
    a = rt.eval_all(getXforLayer(-2))
    b = values_2_classes(getXforLayer(-1))
    fidelity = np.sum(a==b)/len(a)
    if params[VARBOSE] > 0:
        print("[deepred]: Layer {} fidelity {}".format(lastLayerIndex-1, fidelity))
    inf = dict()
    inf["dag_size"] = [len(all_nodes)]
    inf["size_befor_reduc"] = [len(all_nodes)]
    inf["fidelity"] = [fidelity]
    inf["sub_tree_size"] = list()
    inf["sub_tree_acc"] = list()
    inf["sub_tree_time"] = list()
    inf["step_time"] = list()
    if params[SAVE_PROCESS]:
        inf["dag"] = [rt.copy()]
        inf["sub_tree"] = list()
    for actLayer in reversed(range(lastLayerIndex-1)):
        tic = time.time()
        if params[VARBOSE] > 0:
            print("[deepred]: Working on the layer {}".format(actLayer))
        threshold = rt.get_thresholds(all_nodes=all_nodes)
        dt = dict()
        counter = 0
        if params[SAVE_PROCESS]:
            inf["sub_tree"].append(dict())
        inf["sub_tree_acc"].append([None for _ in threshold])
        inf["sub_tree_size"].append([None for _ in threshold])
        inf["sub_tree_time"].append([None for _ in threshold])
        tl = list() # run in parallel
        for index, (i, th) in enumerate(threshold):
            current = DTBuilder(index, i, th)
            tl.append(current)
            current.start()
        for t in tl:
            t.join()

        rt = __merge(rt, dt)
        all_nodes = rt.get_all_nodes()
        prevs = rt.get_predecessor_dict(all_nodes)
        a = rt.eval_all(getXforLayer(actLayer), all_nodes, prevs)
        b = values_2_classes(getXforLayer(-1))
        fidelity = np.sum(a == b) / len(a)
        if params[VARBOSE] > 0:
            print("[deepred]: layer {} fidelity {}".format(actLayer, fidelity))
        inf["size_befor_reduc"].append(len(all_nodes))
        inf["fidelity"].append(fidelity)
        rt = rt.remove_unused_edges(all_nodes, prevs)
        rt.input_size = len(layers_activations[actLayer][0])
        inf["dag_size"].append(len(all_nodes))
        if params[VARBOSE] > 2:
            rt.view_graph(params[OUTPUT_DIR] + "deepred_layer_{}".format(actLayer))
        inf["step_time"].append(time.time()-tic)

    rt.type = "Decition graph generated by DEEPRED"
    rt = rt.delete_redundancy()
    if params[VARBOSE] > 2:
        rt.view_graph(filename=params[OUTPUT_DIR] + "Result")
    params[INF] = inf
    return rt

