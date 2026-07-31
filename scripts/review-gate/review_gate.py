#!/usr/bin/env python3
"""Create, classify, route, and validate layered review artifacts."""
import argparse, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.home()/'.hermes'/'artifacts'/'review'
HIGH = ('auth','authorization','crypto','secret','payment','billing','migration','schema','data deletion','irreversible','concurrency','lock','transaction','cache consistency','remote command','file permission','network boundary','user input','public api','protocol','persistence format','backwards compatibility','production hotfix','release blocker','unverifiable production path')
MEDIUM = ('business logic','multi-file feature','internal api change','new dependency','config change')
LOW = ('documentation','comment','formatting','local test addition','no behaviour change','small refactor')
SEVERITIES = {'blocker','high','medium','low','info'}
CATEGORIES = {'spec','correctness','security','performance','concurrency','compatibility','testing','maintainability'}
L3_FIELDS = {'reviewed_l2_findings','confirmed_findings','rejected_findings','new_findings','critical_invariants','final_recommendation'}


def now(): return datetime.now(timezone.utc).isoformat()
def load(path): return json.loads(Path(path).read_text())
def save(path, data): Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2))


def init(a):
    rid = a.run_id or datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    d = ROOT/rid; d.mkdir(parents=True, exist_ok=True)
    m = {'run_id':rid,'project_root':a.project_root,'goal':a.goal,'acceptance_criteria':a.acceptance,'base_ref':a.base_ref,'head_ref':a.head_ref,'changed_files':a.changed_file or [],'risk_level':a.risk_level,'risk_reasons':a.risk_reason or [],'started_at':now(),'completed_at':None,'status':'in_progress'}
    save(d/'manifest.json',m)
    (d/'implementation-summary.md').write_text('# implementation summary\n')
    print('[OK]',d)


def classify(a):
    m=load(a.manifest); rs=' '.join(map(str,m.get('risk_reasons',[]))).lower()
    m['risk_level']='HIGH' if any(x in rs for x in HIGH) else 'MEDIUM' if any(x in rs for x in MEDIUM) else 'LOW' if any(x in rs for x in LOW) else a.default_level
    m['classified_at']=now(); save(a.manifest,m); print('[OK]',m['risk_level'])


def route(a):
    level=load(a.manifest).get('risk_level','MEDIUM')
    layers={'LOW':['L1','L2-light'],'MEDIUM':['L1','L2'],'HIGH':['L1','L2','L3']}[level]
    print(json.dumps({'risk_level':level,'layers':layers,'l3_required':level=='HIGH'}))


def validate_finding(f,i,errors):
    for k in ('severity','category','title','evidence','impact','recommendation','confidence'):
        if k not in f: errors.append(f'finding[{i}] missing {k}')
    if f.get('severity') not in SEVERITIES: errors.append(f'finding[{i}] bad severity')
    if f.get('category') not in CATEGORIES: errors.append(f'finding[{i}] bad category')
    ev=f.get('evidence',[])
    if f.get('severity')!='info' and (not ev or not all(':' in x for x in ev)): errors.append(f'finding[{i}] lacks path:line')
    c=f.get('confidence');
    if not isinstance(c,(int,float)) or not 0<=c<=1: errors.append(f'finding[{i}] bad confidence')


def validate(a):
    d=load(a.file); errors=[]
    if a.kind=='manifest':
        for k in ('run_id','project_root','goal','acceptance_criteria','base_ref','head_ref','changed_files','risk_level','risk_reasons','started_at','completed_at','status'):
            if k not in d: errors.append('missing '+k)
    elif a.kind=='l1':
        for k in ('passed','commands','summary'): 
            if k not in d: errors.append('missing '+k)
    elif a.kind=='l2':
        for k in ('verdict','findings','commands_reviewed','tests_missing','escalation_required','escalation_reasons'):
            if k not in d: errors.append('missing '+k)
        for i,f in enumerate(d.get('findings',[])): validate_finding(f,i,errors)
    else:
        for k in L3_FIELDS:
            if k not in d: errors.append('missing '+k)
    if errors:
        print('[FAIL] '+'; '.join(errors)); raise SystemExit(1)
    print('[OK]',a.kind,a.file)


def parser():
    p=argparse.ArgumentParser(); s=p.add_subparsers(required=True)
    x=s.add_parser('init'); x.add_argument('--run-id'); x.add_argument('--project-root',required=True); x.add_argument('--goal',required=True); x.add_argument('--acceptance',action='append',default=[]); x.add_argument('--base-ref',default='HEAD'); x.add_argument('--head-ref',default='WORKTREE'); x.add_argument('--changed-file',action='append'); x.add_argument('--risk-level',default='MEDIUM'); x.add_argument('--risk-reason',action='append'); x.set_defaults(fn=init)
    x=s.add_parser('classify'); x.add_argument('--manifest',required=True); x.add_argument('--default-level',choices=['LOW','MEDIUM','HIGH'],default='MEDIUM'); x.set_defaults(fn=classify)
    x=s.add_parser('route'); x.add_argument('--manifest',required=True); x.set_defaults(fn=route)
    x=s.add_parser('validate'); x.add_argument('--kind',choices=['manifest','l1','l2','l3'],required=True); x.add_argument('--file',required=True); x.set_defaults(fn=validate)
    return p

if __name__=='__main__':
    a=parser().parse_args(); a.fn(a)
