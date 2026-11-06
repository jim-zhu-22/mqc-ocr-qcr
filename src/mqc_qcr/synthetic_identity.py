"""Deterministic execution of two maintained rules against a synthetic catalog.

This is an offline test adapter, not a replacement for the deployed LLM service.
It receives no expected answers, scenario labels, sample IDs, or reference links.
"""
import re

PARAMETERS = ('dial_size','mounting_type','process_connection_size','accuracy_class','oil_filled','measuring_range')
TEXT_FIELDS = ('cn_description','cn_po_text','en_description','en_po_text')

def present(value):
    return value is not None and str(value).strip() != ''

def evaluate_identity(material, catalog):
    trace = {'catalog_available':bool(catalog),'required_parameters':list(PARAMETERS)}
    if not catalog:
        return None, None, 'Reference catalog unavailable', trace
    refs = catalog['references']
    params = material.get('key_parameters') or {}
    missing = [k for k in PARAMETERS if not present(params.get(k))]
    trace['missing_parameters'] = missing
    models = {str(material[k]).strip() for k in ('model','spec_model') if present(material.get(k))}
    model_source = 'structured model aliases'
    if len(models)>1:
        trace['conflicting_models']=sorted(models)
        return None,None,'Conflicting model aliases require source selection',trace
    if not models:
        model_source = 'bracketed model in description or purchase text'
        for key in TEXT_FIELDS:
            models.update(re.findall(r'\[([^\[\]]+)\]',str(material.get(key) or '')))
        models.discard('UNK')
        if len(models)>1:
            trace['conflicting_models']=sorted(models)
            return None,None,'Conflicting text models require review',trace
    model = next(iter(models),'')
    model_matches = [r for r in refs if model and r['model']==model]
    param_matches = [] if missing else [r for r in refs if all(str(r['key_parameters'].get(k,''))==str(params[k]) for k in PARAMETERS)]
    # Repeated reference rows with the same identity do not create ambiguity.
    mids = {(r['canonical_manufacturer'],r['model']) for r in model_matches}
    pids = {(r['canonical_manufacturer'],r['model']) for r in param_matches}
    trace.update(model=model, model_source=model_source, model_candidates=[list(x) for x in sorted(mids)], parameter_candidates=[list(x) for x in sorted(pids)], model_reference_ids=[r['reference_id'] for r in model_matches], parameter_reference_ids=[r['reference_id'] for r in param_matches])
    complete = bool(mids) or not missing
    if len(mids)==1 and len(pids)==1 and mids!=pids:
        return complete,None,'Complete model and full parameters identify different catalog items',trace
    if len(mids)==1:
        trace['selected_identity']=list(next(iter(mids)))
        return complete,True,'Complete model identifies one catalog item',trace
    if len(pids)==1:
        trace['selected_identity']=list(next(iter(pids)))
        return complete,True,'Full parameter combination identifies one catalog item',trace
    if len(mids)>1 or (not missing and len(pids)>1):
        return complete,False,'Supplied identification path matches multiple catalog items',trace
    if not missing:
        return complete,None,'Full parameters have no match in the synthetic catalog',trace
    return complete,None,'Insufficient identification information; missing fields do not prove non-uniqueness',trace

def evaluate_semantic_assertion(dsl, material):
    handler = dsl.get('offline_handler')
    if handler not in ('identification_completeness','identification_uniqueness'):
        raise ValueError('Unsupported semantic handler; photos are not a scoring input')
    complete,unique,reason,trace = evaluate_identity(material,material.get('_selection_catalog'))
    passed = complete if handler=='identification_completeness' else unique
    if handler=='identification_completeness' and passed is not None:
        reason = 'Verified complete model or all required fixture parameters are available' if passed else 'No verified complete model and required fixture parameters are missing'
    material.setdefault('_semantic_trace',{})[str(dsl['source_rule_id'])]=trace
    return {'passed':passed,'reason':reason,'evidence_fields':['model','spec_model','key_parameters',*TEXT_FIELDS],'confidence':None}
