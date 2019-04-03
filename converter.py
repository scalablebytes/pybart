import regex as re
import configuration as conf

# constants
two_word_preps_regular = ["across_from", "along_with", "alongside_of", "apart_from", "as_for", "as_from", "as_of", "as_per", "as_to", "aside_from", "based_on", "close_by", "close_to", "contrary_to", "compared_to", "compared_with", " depending_on", "except_for", "exclusive_of", "far_from", "followed_by", "inside_of", "irrespective_of", "next_to", "near_to", "off_of", "out_of", "outside_of", "owing_to", "preliminary_to", "preparatory_to", "previous_to", "prior_to", "pursuant_to", "regardless_of", "subsequent_to", "thanks_to", "together_with"]
two_word_preps_complex = ["apart_from", "as_from", "aside_from", "away_from", "close_by", "close_to", "contrary_to", "far_from", "next_to", "near_to", "out_of", "outside_of", "pursuant_to", "regardless_of", "together_with"]
three_word_preps = ["by_means_of", "in_accordance_with", "in_addition_to", "in_case_of", "in_front_of", "in_lieu_of", "in_place_of", "in_spite_of", "on_account_of", "on_behalf_of", "on_top_of", "with_regard_to", "with_respect_to"]
clause_relations = ["conj", "xcomp", "ccomp", "acl", "advcl", "acl:relcl", "parataxis", "appos", "list"]
w2_quant_mod_of_3w = "(?i:lot|assortment|number|couple|bunch|handful|litany|sheaf|slew|dozen|series|variety|multitude|wad|clutch|wave|mountain|array|spate|string|ton|range|plethora|heap|sort|form|kind|type|version|bit|pair|triple|total)"
w1_quant_mod_of_2w = "(?i:lots|many|several|plenty|tons|dozens|multitudes|mountains|loads|pairs|tens|hundreds|thousands|millions|billions|trillions|[0-9]+s)"
w1_quant_mod_of_2w_det = "(?i:some|all|both|neither|everyone|nobody|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|billion|trillion|[0-9]+)"
relativizing_word_regex = "(?i:that|what|which|who|whom|whose)"


class Restriction(object):
    def __init__(self, dictionary):
        self._dictionary = {"name": None, "gov": None, "no-gov": None, "diff": None,
                            "form": None, "xpos": None, "follows": None, "followed_by": None, "nested": None}
        self._dictionary.update(dictionary)
    
    def __setitem__(self, key, item):
        if key not in self._dictionary:
            raise KeyError("The key {} is not defined.".format(key))
        self._dictionary[key] = item
    
    def __getitem__(self, key):
        return self._dictionary[key]


# ----------------------------------------- matching functions ----------------------------------- #

def neighbors_restrictions(restriction, child, named_nodes):
    if restriction["follows"]:
        follows, _, _ = named_nodes[restriction["follows"]]
        if child.get_conllu_field('id') - 1 != follows.get_conllu_field('id'):
            return False
    
    if restriction["followed"]:
        followed, _, _ = named_nodes[restriction["followed"]][0]
        if child.get_conllu_field('id') + 1 != followed.get_conllu_field('id'):
            return False
    return True


def match(children, restriction_lists, head=None):
    ret = []
    for restriction_list in restriction_lists:
        one_restriction_violated = False
        for restriction in restriction_list:
            restriction_matched = False
            for child in children:
                if restriction["form"]:
                    if not re.match(restriction["form"], child.get_conllu_field('form')):
                        continue
                
                if restriction["xpos"]:
                    if not re.match(restriction["xpos"], child.get_conllu_field('xpos')):
                        continue
                
                relations = [None]
                if restriction["gov"]:
                    relations = child.match_rel(restriction["gov"], head)
                    if len(relations) == 0:
                        continue
                elif head:
                    relations = [b for a, b in child.get_new_relations(head)]
                
                if restriction["no-gov"]:
                    if False in [len(grandchild.match_rel(restriction["no-gov"], child)) == 0 for grandchild in child.get_children()]:
                        continue
                
                nested = []
                if restriction["nested"]:
                    nested = match(
                        child.get_children(),
                        restriction["nested"],
                        head=child)
                    
                    nested = [named_nodes for named_nodes in nested
                              if neighbors_restrictions(restriction, child, named_nodes)]
                    
                    if not nested:
                        continue
                
                if restriction["name"]:
                    for rel in relations:
                        if nested:
                            for d in nested:
                                d[restriction["name"]] = (child, head, rel)
                                ret.append(d)
                        else:
                            ret.append(dict({restriction["name"]: (child, head, rel)}))
                else:
                    ret = nested
                restriction_matched = True
            
            if not restriction_matched:
                one_restriction_violated = True
                break
        
        if not one_restriction_violated:
            return ret
    
    return ret
    

# corrects subjs (includes nsubj/csubj/nsubj:xsubj/csubj:xsubj) to subjpass,
# if they are a sibling of auxpass.
def correct_subj_pass(sentence):
    restriction_lists = \
    [[
        Restriction({"nested":
        [[
            Restriction({"gov": 'auxpass'}),
            Restriction({"gov": "^(.subj|.subj:xsubj)$", "name": "subj"})
        ]]})
    ]]
    
    ret = dict()
    if not match(sentence.values(), restriction_lists, ret):
        return
    
    # rewrite graph: for every subject add a 'pass' and replace in graph node
    for subj_source, subj_head, subj_rel in ret['subj']:
        substitute_rel = re.sub("subj", "subjpass", subj_rel)
        subj_source.replace_edge(subj_rel, substitute_rel, subj_head, subj_head)


# add 'agent' to nmods if it is cased by 'by', and have an auxpass sibling
def passive_agent(sentence):
    restriction_lists = \
    [[
        Restriction({"nested":
        [[
            Restriction({"gov": 'nmod', "name": "mod", "nested":
            [[
                Restriction({"gov": 'case', "form": "^(?i:by)$"})
            ]]}),
            Restriction({"gov": "auxpass"})
        ]]})
    ]]
    ret = dict()
    if not match(sentence.values(), restriction_lists, ret):
        return

    # rewrite graph: for every nmod add ':agent' to the graph node relation
    for mod_source, mod_head, mod_rel in ret['mod']:
        mod_source.replace_edge(mod_rel,  mod_rel + ":agent", mod_head, mod_head)


def build_strings_to_add(ret):
    # we need to create a concat string for every marker neighbor chain
    # actually it should never happen that they are separate, but nonetheless we add relation if so,
    # this might result in multi-graph
    # e.g 'in front of' should be [in_front_of] if they all follow but [in, front_of],
    # if only 'front' and 'of' are follow (and 'in' is separated).
    strs_to_add = []
    
    for c1_source, _, _ in ret['c1']:
        # add the first word
        strs_to_add += [c1_source.get_conllu_field('form')]
        if 'c2' in ret:
            prev = c1_source
            for c2_source, _, _ in ret['c2']:
                # concat every following marker, or start a new string if not
                if prev.get_conllu_field('id') == c2_source.get_conllu_field('id') - 1:
                    strs_to_add[-1] += '_' + c2_source.get_conllu_field('form')
                else:
                    strs_to_add.append(c2_source.get_conllu_field('form'))
                prev = c2_source
    
    return strs_to_add


def prep_patterns(sentence, first_gov, second_gov):
    restriction_lists = \
    [[
        Restriction({"name": "gov", "nested":
        [[
            Restriction({"gov": first_gov, "name": "mod", "nested":
            [[
                Restriction({"gov": second_gov, "name": "c1", "nested":
                [[
                    Restriction({"gov": 'mwe', "name": "c2"})
                ]]})
            ]]})
        ],
        [
            Restriction({"gov": first_gov, "name": "mod", "nested":
            [[
                Restriction({"gov": second_gov, "name": "c1", "form": "(?!(^(?i:by)$))."})
            ]]})
        ]]})
    ]]
    ret = dict()
    if not match(sentence.values(), restriction_lists, ret):
        return
    
    for mod_source, mod_head, mod_rel in ret['mod']:
        strs_to_add = build_strings_to_add(ret)
        mod_source.remove_edge(mod_rel, mod_head)
        for str_to_add in strs_to_add:
            mod_source.add_edge(mod_rel + ":" + str_to_add.lower(), mod_head)


# Adds the type of conjunction to all conjunct relations
def conj_info(sentence):
    restriction_lists = \
    [[
        Restriction({"nested":
        [[
            Restriction({"gov": "cc", "name": "cc"}),
            Restriction({"gov": "^conj$", "name": "conj"})
        ]]})
    ]]
    ret = dict()
    if not match(sentence.values(), restriction_lists, ret):
        return
    
    # this was added to get the first cc, because it should be applied on all conj's that precedes it
    cur_form = sorted([(triplet[0].get_conllu_field('id'), triplet) for triplet in ret["cc"]])[0][1][0].get_conllu_field('form')
    for (_, (cc_or_conj_source, cc_or_conj_head, cc_or_conj_rel)) in \
            sorted([(triplet[0].get_conllu_field('id'), triplet) for triplet in ret["cc"] + ret["conj"]]):
        if cc_or_conj_rel == "cc":
            cur_form = cc_or_conj_source.get_conllu_field('form')
        else:
            cc_or_conj_source.replace_edge(
                cc_or_conj_rel, cc_or_conj_rel + ":" + cur_form, cc_or_conj_head, cc_or_conj_head)


def conjoined_subj(sentence):
    restriction_lists = \
    [[
        Restriction({"nested":
        [[
            Restriction({"gov": "^((?!root|case|nsubj|dobj).)*$", "name": "gov", "nested":
            [[
                # TODO - I don't fully understand why SC decided to add this rcmod condition, and I believe they have a bug:
                #   (rcmodHeads.contains(gov) && rcmodHeads.contains(dep)) should be ||, and so I coded.
                Restriction({"gov": "rcmod"}),
                Restriction({"gov": ".*conj.*", "name": "dep"})
            ],
            [
                Restriction({"gov": ".*conj.*", "name": "dep", "nested":
                [[
                    Restriction({"gov": "rcmod"})
                ]]})
            ]]})
        ],
        [
            Restriction({"gov": "^((?!root|case).)*$", "no-gov": "rcmod", "name": "gov", "nested":
            [[
                Restriction({"gov": ".*conj.*", "no-gov": "rcmod", "name": "dep"})
            ]]})
        ]]})
    ]]
    ret = dict()
    if not match(sentence.values(), restriction_lists, ret):
        return
    
    for _, gov_head, gov_rel in ret['gov']:
        for dep_source, _, _ in ret['dep']:
            dep_source.add_edge(gov_rel, gov_head)


def conjoined_verb(sentence):
    restriction_lists = \
    [[
        Restriction({"nested":
        [[
            Restriction({"gov": "conj", "no-gov": ".subj", "name": "conj", "xpos": "(VB|JJ)", "nested":
            [[
                Restriction({"gov": "auxpass", "name": "auxpass"})
            ]]}),
            Restriction({"gov": ".subj", "name": "subj"})
        ],
        [
            Restriction({"gov": "conj", "no-gov": ".subj|auxpass", "name": "conj", "xpos": "(VB|JJ)"}),
            Restriction({"gov": ".subj", "name": "subj"})
        ]]})
    ]]
    ret = dict()
    if not match(sentence.values(), restriction_lists, ret):
        return
    
    for subj_source, _, subj_rel in ret['subj']:
        for conj_source, _, _ in ret['conj']:
            # TODO - this could be out into restrictions, but it would be a huge add-up,
            # so rather stay with this small if statement
            if subj_rel.endswith("subjpass") and \
                            subj_source.get_conllu_field('xpos') in ["VB", "VBZ", "VBP", "JJ"]:
                subj_rel = subj_rel[:-4]
            elif subj_rel.endswith("subj") and "auxpass" in ret:
                subj_rel += "pass"
            
            subj_source.add_edge(subj_rel, conj_source)
            # TODO - we need to add the aux relation (as SC say they do but not in the code)
            #   and the obj relation, which they say they do and also coded, but then commented out...


def xcomp_propagation_per_type(sentence, restriction):
    restriction_lists = \
    [[
        Restriction({"nested":
        [
            restriction + [Restriction({"gov": "dobj", "name": "obj"})],
            restriction
        ]})
    ]]
    ret = dict()
    if not match(sentence.values(), restriction_lists, ret):
        return
    
    if 'obj' in ret:
        for obj_source, _, _ in ret['obj']:
            for _, dep_head, _ in ret['dep']:
                if dep_head not in obj_source.get_parents():
                    obj_source.add_edge("nsubj:xsubj", dep_head)
    else:
        for subj_source, _, _ in ret['subj']:
            for _, dep_head, _ in ret['dep']:
                if dep_head not in subj_source.get_parents():
                    subj_source.add_edge("nsubj:xsubj", dep_head)


def xcomp_propagation(sentence):
    to_xcomp_rest = \
        [
            Restriction({"gov": "xcomp", "no-gov": "^(nsubj.*|aux|mark)$", "name": "dep", "form": "^(?i:to)$"}),
            Restriction({"gov": "nsubj.*", "name": "subj"}),
        ]
    basic_xcomp_rest = \
        [
            Restriction({"gov": "xcomp", "no-gov": "nsubj.*", "name": "dep", "form": "(?!(^(?i:to)$)).", "nested":
            [[
                Restriction({"gov": "^(aux|mark)$"})
            ]]}),
            Restriction({"gov": "nsubj.*", "name": "subj"}),
        ]

    for xcomp_restriction in [to_xcomp_rest, basic_xcomp_rest]:
        xcomp_propagation_per_type(sentence, xcomp_restriction)


def process_simple_2wp(sentence):
    for two_word_prep in two_word_preps_regular:
        w1_form, w2_form = two_word_prep.split("_")
        restriction_lists = \
        [[
            Restriction({"name": "gov", "nested":
            [[
                Restriction({"gov": "(case|advmod)", "no-gov": ".*", "name": "w1", "form": "^" + w1_form + "$"}),
                Restriction({"gov": "case", "no-gov": ".*", "follows": "w1", "name": "w2", "form": "^" + w2_form + "$"})
            ]]})
        ]]
        ret = dict()
        if not match(sentence.values(), restriction_lists, ret):
            continue
        
        for gov, _, _ in ret['gov']:
            for (w1, w1_head, w1_rel), (w2, w2_head, w2_rel) in zip(ret['w1'], ret['w2']):
                w1.replace_edge(w1_rel, "case", w1_head, w1_head)
                w2.replace_edge(w2_rel, "mwe", w2_head, w1)


def process_complex_2wp(sentence):
    for two_word_prep in two_word_preps_complex:
        w1_form, w2_form = two_word_prep.split("_")
        restriction = \
            Restriction({"name": "gov", "nested": [[
                Restriction({"name": "w1", "followed_by": "w2", "form": "^" + w1_form + "$", "nested":
                [[
                    Restriction({"gov": "nmod", "name": "gov2", "nested":
                    [[
                        Restriction({"gov": "case", "no-gov": ".*", "name": "w2", "form": "^" + w2_form + "$"}),
                    ]]}),
                ]]})
            ]]})
        
        ret = dict()
        if not match(sentence.values(), [[restriction]], ret):
            continue
        
        for gov, _, _ in ret['gov']:
            for gov2, gov2_head, gov2_rel in ret['gov2']:
                for w1, _, w1_rel in ret['w1']:
                    # reattach w1 sons to gov2
                    w1_has_cop_child = False
                    gov2.remove_edge()
                    for child in w1.get_children():
                        for child_head, child_rel in child.get_new_relations(given_head=w1.get_conllu_field('id')):
                            if child_rel == "cop":
                                w1_has_cop_child = True
                            child.replace_edge(child_rel, child_rel, w1, gov2)
                    
                    # Determine the relation to use.
                    rel = w1_rel if w1_has_cop_child and (w1_rel in clause_relations) else gov2_rel
                    
                    # replace gov2's governor
                    w1.remove_edge(w1_rel, gov)
                    gov2.replace_edge(gov2_rel, rel, w1, gov)
                    
                    w1.remove_all_edges()
                    w1.add_edge("case", gov2)
                    for w2, _, _ in ret['w2']:
                        w2.remove_all_edges()
                        w2.add_edge("mwe", w1)


def process_3wp(sentence):
    for three_word_prep in three_word_preps:
        w1_form, w2_form, w3_form = three_word_prep.split("_")
        restriction = \
            Restriction({"name": "gov", "nested":
            [[
                Restriction({"name": "w2", "followed_by":"w3", "follows": "w1", "form": "^" + w2_form + "$", "nested":
                [[
                    Restriction({"gov": "(nmod|acl|advcl)", "name": "gov2", "nested":
                    [[
                        Restriction({"gov": "(case|mark)", "no-gov": ".*", "name": "w3", "form": "^" + w3_form + "$"}),
                    ]]}),
                    Restriction({"gov": "case", "no-gov": ".*", "name": "w1", "form": "^" + w1_form + "$"})
                ]]})
            ]]})
        
        ret = dict()
        if not match(sentence.values(), [[restriction]], ret):
            continue
        
        for gov2, gov2_head, gov2_rel in ret['gov2']:
            for w2, w2_head, w2_rel in ret['w2']:
                # Determine the relation to use. If it is a relation that can
                # join two clauses and w1 is the head of a copular construction,
                # then use the relation of w1 and its parent. Otherwise use the relation of edge.
                case = "case"
                rel = w2_rel
                if (w2_rel == "nmod") and (gov2_rel in ["acl", "advcl"]):
                    rel = gov2_rel
                    case = "mark"
                
                gov2.replace_edge(gov2_rel, rel, w2, w2_head)
                # reattach w2 sons to gov2
                for child in w2.get_children():
                    for child_head, child_rel in child.get_new_relations(given_head=w2):
                        child.replace_edge(child_rel, child_rel, w2, gov2)
                
                w2.remove_all_edges()
                
                for w1, _, _ in ret['w1']:
                    w1.remove_all_edges()
                    w1.add_edge(case, gov2)
                    w2.add_edge("mwe", w1)
                    for w3, w3_head, w3_rel in ret['w3']:
                        w3.remove_all_edges()
                        w3.add_edge("mwe", w1)


def demote_quantificational_modifiers_3w(sentence):
    restriction = \
        Restriction({"name": "gov", "nested":
        [[
            Restriction({"name": "w2", "no-gov": "amod", "follows": "w3", "form": w2_quant_mod_of_3w, "nested":
            [[
                Restriction({"gov": "det", "name": "w1", "form": "(?i:an?)"}),
                Restriction({"gov": "nmod", "xpos": "(NN.*|PRP.*)", "name": "gov2", "nested":
                [[
                    Restriction({"gov": "case", "form": "(?i:of)", "name": "w3"})
                ]]})
            ]]})
        ]]})
    
    ret = dict()
    if not match(
            sentence.values(),
            [[restriction]],
            ret):
        return
    
    for gov2, gov2_head, gov2_rel in ret['gov2']:
        for w1, w1_head, w1_rel in ret['w1']:
            w1.remove_all_edges()
            w1.add_edge("det:qmod", gov2)
            for w2, w2_head, w2_rel in ret['w2']:
                w2.remove_all_edges()
                gov2.replace_edge(gov2_rel, w2_rel, gov2_head, w2_head)
                w2.add_edge("mwe", w1)
                for w3, w3_head, w3_rel in ret['w3']:
                    w3.remove_all_edges()
                    w3.add_edge("mwe", w1)


def demote_2w_per_type(sentence, rl):
    ret = dict()
    if not match(
            sentence.values(),
            [[rl]],
            ret):
        return
    
    for gov2, gov2_head, gov2_rel in ret['gov2']:
        for w1, w1_head, w1_rel in ret['w1']:
            w1.remove_all_edges()
            gov2.replace_edge(gov2_rel, w1_rel, gov2_head, w1_head)
            w1.add_edge("det:qmod", gov2)
            for w2, w2_head, w2_rel in ret['w2']:
                w2.remove_all_edges()
                w2.add_edge("mwe", w1)


def demote_quantificational_modifiers_2w(sentence):
    restriction = \
        Restriction({"name": "gov", "nested":
        [[
            Restriction({"name": "w1", "followed_by": "w2", "form": w1_quant_mod_of_2w, "nested":
            [[
                Restriction({"gov": "nmod", "xpos": "(NN.*|PRP.*)", "name": "gov2", "nested":
                [[
                    Restriction({"gov": "case", "form": "(?i:of)", "name": "w2"})
                ]]})
            ]]})
        ]]})
    restriction_det = \
        Restriction({"name": "gov", "nested":
        [[
            Restriction({"name": "w1", "followed_by": "w2", "form": w1_quant_mod_of_2w_det, "nested":
            [[
                Restriction({"gov": "nmod", "xpos": "(NN.*)", "name": "gov2", "nested":
                [[
                    Restriction({"gov": "det", "name": "det"}),
                    Restriction({"gov": "case", "followed_by": "det", "form": "(?i:of)", "name": "w2"})
                ]]})
            ],
            [
                Restriction({"gov": "nmod", "xpos": "(PRP.*)", "name": "gov2", "nested":
                [[
                    Restriction({"gov": "case", "form": "(?i:of)", "name": "w2"})
                ]]})
            ]]})
        ]]})
    
    for rl in [restriction, restriction_det]:
        demote_2w_per_type(sentence, rl)
 

def add_ref_and_collapse(sentence):
    child_rest = Restriction({"name": "child_ref", "form": relativizing_word_regex})
    grandchild_rest = \
        Restriction({"nested":
            [[
                Restriction({"name": "grand_ref", "form": relativizing_word_regex})
            ]]})
    restriction_lists = \
    [[
        Restriction({"name": "gov", "nested":
        [[
            Restriction({"gov": 'acl:relcl', "nested":
            [
                [grandchild_rest, child_rest],
                [grandchild_rest],
                [child_rest]
            ]}),
        ]]})
    ]]
    
    ret = dict()
    if not match(sentence.values(), restriction_lists, ret):
        return
    
    for gov, gov_head, gov_rel in ret['gov']:
        leftmost = None
        descendants = ([d for d, _, _ in ret['grand_ref']] if 'grand_ref' in ret else []) + \
                     ([d for d, _, _ in ret['child_ref']] if 'child_ref' in ret else [])
        for descendant in descendants:
            if (not leftmost) or descendant.get_conllu_field('id') < leftmost.get_conllu_field('id'):
                leftmost = descendant
        
        for parent, edge in leftmost.get_new_relations():
            leftmost.remove_edge(edge, parent)
            gov.add_edge(edge, parent)
        
        leftmost.add_edge("ref", gov)


# Expands prepositions with conjunctions such as in the sentence
# "Bill flies to and from Serbia." by copying the verb resulting
# in the following relations:
#   conj:and(flies, flies') # new
#   cc(to, and)
#   conj(to, from)
#   case(Serbia, to)
#   nmod(flies, Serbia)
#   nmod(flies', Serbia) # new
# The label of the conjunct relation includes the conjunction type
# because if the verb has multiple cc relations then it can be impossible
# to infer which coordination marker belongs to which conjuncts.
def expand_prep_conjunctions(sentence):
    rl = [[Restriction({"nested": [[
            Restriction({"nested": [[
                Restriction({"gov": "case", "name": "gov", "nested": [[
                    Restriction({"gov": "cc", "name": "cc"}),
                    Restriction({"gov": "conj", "name": "conj"})
                ]]})
            ]]})
        ]]})
    ]]
    ret = dict()
    
    if not match(sentence.values(), rl, ret):
        return
    for gov, _, _ in ret['gov']:
        cur_form = None
        i = 0
        # sort the cc's and conj's found and iterate them
        # TODO - some of this code was copied from conj_info and from expand_pp_conjunctions - try to share code
        for (_, (cc_or_conj_source, cc_or_conj_head, cc_or_conj_rel)) in \
                sorted([(triplet[0].get_conllu_field('id'), triplet) for triplet in ret["cc"] + ret["conj"]]):
            if cc_or_conj_rel == "cc":
                # save cc's form
                cur_form = cc_or_conj_source.get_conllu_field('form')
            else:
                # per parent per grandpa: copy the grandpa and:
                # add conj:'cc_form'(grandpa, copy_node)
                # add 'rel':'conj_form'(copy_node, parent)
                i += 1
                for parent, _ in gov.get_new_relations():
                    for grandpa, grandpa_rel in parent.get_new_relations():
                        new_id = grandpa.get_conllu_field('id') + (0.1 * i)
                        copy_node = grandpa.copy(
                            new_id=new_id,
                            head="_",
                            deprel="_",
                            misc="CopyOf=%d" % grandpa.get_conllu_field('id'))
                        parent.add_edge(grandpa_rel + ":" + cc_or_conj_source.get_conllu_field('form'), copy_node)
                        copy_node.add_edge("conj:" + cur_form, grandpa)
                        sentence[new_id] = copy_node


# Expands PPs with conjunctions such as in the sentence
# "Bill flies to France and from Serbia." by copying the verb
# that governs the prepositional phrase resulting in the following
# relations:
#   conj:and(flies, flies') # new
#   case(France, to)
#   cc(flies, and) # new
#   case(Serbia, from)
#   nmod(flies, France)
#   nmod(flies', Serbia) # new
# while those where removed:
#   cc(France-4, and-5)
#   conj(France-4, Serbia-7)
# The label of the conjunct relation includes the conjunction type
# because if the verb has multiple cc relations then it can be impossible
# to infer which coordination marker belongs to which conjuncts.
def expand_pp_conjunctions(sentence):
    rl = [[Restriction({"nested": [[
            Restriction({"gov": "^(nmod|acl|advcl)$", "name": "gov", "nested": [[
                Restriction({"gov": "case"}),
                Restriction({"gov": "cc", "name": "cc"}),
                Restriction({"gov": "conj", "name": "conj", "nested": [[
                    Restriction({"gov": "case"})
                ]]})
            ]]})
        ]]})
    ]]
    
    ret = dict()
    if not match(sentence.values(), rl, ret):
        return
    
    for gov, _, _ in ret['gov']:
        cur_form = None
        i = 0
        # sort the cc's and conj's found and iterate them
        # TODO - some of this code was copied from conj_info - try to share code
        for (_, (cc_or_conj_source, cc_or_conj_head, cc_or_conj_rel)) in \
                sorted([(triplet[0].get_conllu_field('id'), triplet) for triplet in ret["cc"] + ret["conj"]]):
            if cc_or_conj_rel == "cc":
                # save cc's form and remove cc('gov', 'cc')
                cur_form = cc_or_conj_source.get_conllu_field('form')
                cc_or_conj_source.remove_edge(cc_or_conj_rel, cc_or_conj_head)
                
                # per parent add cc('to_copy', cc)
                for to_copy, rel in gov.get_new_relations():
                    cc_or_conj_source.add_edge("cc", to_copy)
            
            else:
                # remove conj('gov', 'conj')
                cc_or_conj_source.remove_edge(cc_or_conj_rel, cc_or_conj_head)
                
                # per parent: create a copy node for the parent,
                # rel(copy_node,'conj'), add conj:cc_info('to_copy', copy_node)
                i += 1
                for to_copy, rel in gov.get_new_relations():
                    new_id = to_copy.get_conllu_field('id') + (0.1 * i)
                    copy_node = to_copy.copy(
                        new_id=new_id,
                        head="_",
                        deprel="_",
                        misc="CopyOf=%d" % to_copy.get_conllu_field('id'))
                    cc_or_conj_source.add_edge(rel, copy_node)
                    copy_node.add_edge("conj:" + cur_form, to_copy)
                    sentence[new_id] = copy_node


def convert_sentence(sentence):
    # correctDependencies - correctSubjPass, processNames and removeExactDuplicates.
    # the last two have been skipped. processNames for future decision, removeExactDuplicates for redundancy.
    correct_subj_pass(sentence)

    if conf.enhanced_plus_plus:
        # processMultiwordPreps: processSimple2WP, processComplex2WP, process3WP
        process_simple_2wp(sentence)
        process_complex_2wp(sentence)
        process_3wp(sentence)
        # demoteQuantificationalModifiers
        demote_quantificational_modifiers_3w(sentence)
        demote_quantificational_modifiers_2w(sentence)
        # add copy nodes: expandPPConjunctions, expandPrepConjunctions
        expand_pp_conjunctions(sentence)
        expand_prep_conjunctions(sentence)
    
    # addCaseMarkerInformation
    passive_agent(sentence)
    prep_patterns(sentence, '^nmod$', 'case')
    if not conf.enhance_only_nmods:
        prep_patterns(sentence, '^(advcl|acl)$', '^(mark|case)$')
    
    # addConjInformation
    conj_info(sentence)
    
    # referent: addRef, collapseReferent
    if conf.enhanced_plus_plus:
        add_ref_and_collapse(sentence)
        
    # treatCC
    conjoined_subj(sentence)
    conjoined_verb(sentence)
    
    # addExtraNSubj
    xcomp_propagation(sentence)
    
    # correctSubjPass
    # TODO - why again?
    correct_subj_pass(sentence)
    
    return sentence


def convert(parsed):
    converted_sentences = []
    for sentence in parsed:
        converted_sentences.append(convert_sentence(sentence))
    return converted_sentences
