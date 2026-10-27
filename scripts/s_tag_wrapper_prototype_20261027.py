#!/usr/bin/env python3
"""Read-only tag inventory and fresh wrapper prototypes; never launches a compiler."""
from __future__ import annotations
import argparse
import ast
from functools import lru_cache
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "runs/s-tag-wrapper-2026-10-27"
UNITS = ("aq-024-6f6781246415", "aq-017-9703bbce0c43")
REQUIRED = {"RewardsExtended", "ZoneIdInclusionProver", "DataEscrowElGamalEncryption", "TrustProvidersKyt", "ZSwapV1"}
LEX = re.compile(r'\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|0[xX][0-9a-fA-F]+|[0-9][0-9_]*|<==|==>|<--|-->|===|==|!=|<=|>=|&&|\|\||\*\*=|\*\*|\+\+|--|\+=|-=|\*\*=|\*=|/=|%=|\\=|<<=|>>=|&=|\|=|\^=|<<|>>|[^\s]')
IDENT = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*$')

class Refusal(ValueError):
    pass

@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    line: int


def guard():
    if os.getpriority(os.PRIO_PROCESS, 0) < 19:
        raise RuntimeError("nice 19 required")
    if shutil.disk_usage(ROOT).free < 15 * 2**30:
        # The shared recorder implements the requested five-minute/30-minute pause.
        from s_tag_wrapper_run_20261027 import gate
        gate()


def safe(value):
    p = Path(value)
    p = (p if p.is_absolute() else ROOT / p).resolve()
    if ("n6-a-remeasure-2026-10-25.noindex" in p.parts or
        str(p).startswith("/Volumes/zkfdo-jcache") or
        any(part.startswith(("n6-b6", "h1-")) for part in p.parts)):
        raise Refusal("forbidden input path")
    return p


def sha(data):
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=128)
def tokenize(source):
    result = []
    line, previous = 1, 0
    for m in LEX.finditer(source):
        text = m.group()
        line += source.count("\n", previous, m.start())
        start_line = line
        line += text.count("\n")
        previous = m.end()
        if text.isspace() or text.startswith("//") or text.startswith("/*"):
            continue
        result.append(Token(text, m.start(), m.end(), start_line))
    return result


def match(tokens, start, left="(", right=")"):
    if start >= len(tokens) or tokens[start].text != left:
        raise Refusal(f"expected {left}")
    depth = 0
    for i in range(start, len(tokens)):
        if tokens[i].text == left:
            depth += 1
        elif tokens[i].text == right:
            depth -= 1
            if depth == 0:
                return i
    raise Refusal(f"unbalanced {left}{right}")


def split_top(tokens, separator=","):
    chunks, current, stack = [], [], []
    for token in tokens:
        if token.text in ("(", "[", "{"):
            stack.append(token.text)
        elif token.text in (")", "]", "}"):
            if not stack or {"(": ")", "[": "]", "{": "}"}[stack.pop()] != token.text:
                raise Refusal("unbalanced expression")
        if token.text == separator and not stack:
            chunks.append(current)
            current = []
        else:
            current.append(token)
    if stack:
        raise Refusal("unbalanced expression")
    if current:
        chunks.append(current)
    return chunks


def text_of(tokens):
    return " ".join(t.text for t in tokens)


@lru_cache(maxsize=256)
def definitions(source, kind="template"):
    tokens = tokenize(source)
    found = []
    for i, token in enumerate(tokens):
        if token.text != kind or i + 2 >= len(tokens) or not IDENT.fullmatch(tokens[i+1].text) or tokens[i+2].text != "(":
            continue
        close = match(tokens, i+2)
        if close + 1 >= len(tokens) or tokens[close+1].text != "{":
            continue
        end = match(tokens, close+1, "{", "}")
        parameters = split_top(tokens[i+3:close])
        if any(len(p) != 1 or not IDENT.fullmatch(p[0].text) for p in parameters):
            raise Refusal("unsupported template/function parameter declaration")
        found.append({"name": tokens[i+1].text, "parameters": [p[0].text for p in parameters],
                      "body": tokens[close+2:end], "line": token.line})
    return found


def legacy_wrapper(source_path, template, arguments):
    include = str(source_path).replace("\\", "/").replace('"', '\\"')
    return f'pragma circom 2.1.6;\n\ninclude "{include}";\n\ncomponent main = {template}({", ".join(arguments)});\n'


def original_call(wrapper):
    tokens = tokenize(wrapper)
    includes = []
    for i,t in enumerate(tokens):
        if t.text == "include" and i+1 < len(tokens) and tokens[i+1].text.startswith('"'):
            includes.append(json.loads(tokens[i+1].text))
    mains = []
    for i in range(len(tokens)-4):
        if [t.text for t in tokens[i:i+3]] == ["component", "main", "="]:
            if tokens[i+4].text != "(":
                raise Refusal("unsupported original main call")
            close = match(tokens, i+4)
            args = split_top(tokens[i+5:close])
            # Preserve literal spelling/spacing inside each concrete argument.
            values = [wrapper[a[0].start:a[-1].end].strip() for a in args]
            mains.append((tokens[i+3].text, values))
    if len(includes) != 1 or len(mains) != 1:
        raise Refusal("requires one direct include and one literal main call")
    return safe(includes[0]), *mains[0]


def inspect_ports(definition):
    body = definition["body"]
    ports, variables, depth, i = [], {}, 0, 0
    while i < len(body):
        t = body[i]
        if t.text == "signal" and i+1 < len(body) and body[i+1].text in {"input", "output"}:
            if depth:
                raise Refusal("input/output declaration inside a control-flow block")
            direction = body[i+1].text
            cursor, tags = i+2, []
            if body[cursor].text == "{":
                close = match(body, cursor, "{", "}")
                groups = split_top(body[cursor+1:close])
                if not groups or any(len(g)!=1 or not IDENT.fullmatch(g[0].text) for g in groups):
                    raise Refusal("tag declaration is not an exact identifier list")
                tags = [g[0].text for g in groups]
                if len(tags) != len(set(tags)):
                    raise Refusal("duplicate tag names")
                cursor = close+1
            # Multiple scalar/array names in one declaration retain their shared tags.
            while True:
                if cursor >= len(body) or not IDENT.fullmatch(body[cursor].text):
                    raise Refusal("unsupported signal declaration")
                name, line = body[cursor].text, body[cursor].line
                cursor += 1
                dims = []
                while cursor < len(body) and body[cursor].text == "[":
                    close = match(body, cursor, "[", "]")
                    dims.append(body[cursor+1:close])
                    cursor = close+1
                ports.append({"name": name, "direction": direction, "tags": tags[:], "dimensions": dims, "line": line})
                if cursor >= len(body):
                    raise Refusal("unterminated signal declaration")
                if body[cursor].text == ",":
                    cursor += 1
                    continue
                if body[cursor].text not in {";", "<==", "<--", "="}:
                    raise Refusal("unsupported signal declaration suffix")
                # An initializer remains exclusively in the original target body.
                while cursor < len(body) and body[cursor].text != ";":
                    cursor += 1
                if cursor == len(body):
                    raise Refusal("unterminated signal initializer")
                i = cursor+1
                break
            continue
        if t.text == "var" and depth == 0 and (i == 0 or body[i-1].text in {";", "}"}):
            end = i
            while end < len(body) and body[end].text != ";":
                end += 1
            statement = body[i+1:end]
            if len(statement)>=3 and IDENT.fullmatch(statement[0].text) and statement[1].text == "=" and len(split_top(statement)) == 1:
                name = statement[0].text
                if name in variables:
                    variables[name]["ambiguous"] = True
                else:
                    variables[name] = {"expression": statement[2:], "line": t.line, "position": i, "ambiguous": False}
        if t.text == "{": depth += 1
        elif t.text == "}": depth -= 1
        i += 1
    names = [p["name"] for p in ports]
    if len(names) != len(set(names)):
        raise Refusal("duplicate interface signal names")
    return ports, variables


def access_evidence(definition, ports, path):
    body = definition["body"]
    tagged = {p["name"]: set(p["tags"]) for p in ports if p["direction"] == "input" and p["tags"]}
    evidence = []
    for i,t in enumerate(body):
        if t.text not in tagged:
            continue
        cursor = i+1
        while cursor < len(body) and body[cursor].text == "[":
            cursor = match(body,cursor,"[","]")+1
        if cursor+1 < len(body) and body[cursor].text == "." and body[cursor+1].text in tagged[t.text]:
            tag = body[cursor+1].text
            following = body[cursor+2].text if cursor+2<len(body) else ""
            evidence.append({"input":t.text,"tag":tag,"path":str(path),"line":t.line,
                             "kind":"target_tag_write" if following in {"=","+=","-=","*=","/="} else "target_tag_read",
                             "expression":text_of(body[i:cursor+2])})
    return evidence


def parent_write_evidence(template, ports, sources):
    tags = {p["name"]:set(p["tags"]) for p in ports if p["direction"]=="input" and p["tags"]}
    evidence = []
    if not tags:
        return evidence
    for path,source in sources.items():
        for parent in definitions(source):
            body = parent["body"]
            components = set()
            for i in range(len(body)-2):
                # The target call must be assigned to an identified component slot.
                if body[i].text == "=" and body[i+1].text==template and body[i+2].text=="(":
                    start = i-1
                    while start>=0 and body[start].text not in {";","{","}","component"}:
                        start -= 1
                    lhs = body[start+1:i]
                    if lhs and IDENT.fullmatch(lhs[0].text) and all(t.text not in {".",","} for t in lhs):
                        components.add(lhs[0].text)
            for i,t in enumerate(body):
                if t.text not in components:
                    continue
                cursor=i+1
                while cursor<len(body) and body[cursor].text=="[":cursor=match(body,cursor,"[","]")+1
                if cursor+1>=len(body) or body[cursor].text!="." or body[cursor+1].text not in tags:continue
                port=body[cursor+1].text;cursor+=2
                while cursor<len(body) and body[cursor].text=="[":cursor=match(body,cursor,"[","]")+1
                if cursor+2>=len(body) or body[cursor].text!="." or body[cursor+1].text not in tags[port] or body[cursor+2].text!="=":continue
                tag=body[cursor+1].text;end=cursor+3
                while end<len(body) and body[end].text!=";":end+=1
                evidence.append({"path":str(path),"line":t.line,"parent_template":parent["name"],"component":t.text,
                                 "input":port,"tag":tag,"value_expression":text_of(body[cursor+3:end]),
                                 "binding":"candidate parent write; not matched to this concrete isolated instance"})
    return evidence


def variable_assignment_count(tokens, name):
    assignments={"=","+=","-=","*=","/=","%=","\\=","**=","<<=",">>=","&=","|=","^=","++","--"}
    count=0
    for i,t in enumerate(tokens):
        if t.text!=name:continue
        cursor=i+1
        while cursor<len(tokens) and tokens[cursor].text=='[':
            cursor=match(tokens,cursor,'[',']')+1
        if (cursor<len(tokens) and tokens[cursor].text in assignments) or (i>0 and tokens[i-1].text in {'++','--'}):count+=1
    return count


def dimension_declarations(definition, ports, variables, sources):
    # Expressions are copied exactly, never numerically guessed. Only immutable
    # scalar locals/parameters and source-defined pure functions are admitted.
    functions = {}
    for path,source in sources.items():
        for f in definitions(source,"function"):
            functions.setdefault(f["name"],[]).append(f)
    checked_functions=set()
    def pure_function(name,visiting):
        if name in checked_functions:return
        if name in visiting:raise Refusal("recursive dimension function is not supported by this prototype")
        defs=functions.get(name,[])
        if len(defs)!=1:raise Refusal(f"dimension function {name} is missing or ambiguous")
        tokens=defs[0]["body"]
        forbidden={"signal","component","bus","log","<==","<--","==>","-->","==="}
        if any(t.text in forbidden for t in tokens):raise Refusal(f"dimension function {name} is not proven source-only")
        for i,t in enumerate(tokens[:-1]):
            if IDENT.fullmatch(t.text) and tokens[i+1].text=="(" and t.text not in {"if","for","while","assert"}:
                pure_function(t.text,visiting|{name})
        checked_functions.add(name)
    needed=set();visiting=set()
    def expression(tokens):
        if not tokens:raise Refusal("empty array dimension")
        allowed={"+","-","*","/","\\","%","**","(",")","[","]",",","<",">","<=",">=","==","!=","&&","||","!","~","&","|","^","<<",">>","?",":"}
        for i,t in enumerate(tokens):
            if IDENT.fullmatch(t.text):
                if i+1<len(tokens) and tokens[i+1].text=="(":pure_function(t.text,set())
                elif t.text in definition['parameters']:continue
                elif t.text in variables:variable(t.text)
                else:raise Refusal(f"array dimension depends on unresolved value {t.text}")
            elif not re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9][0-9_]*)',t.text) and t.text not in allowed:
                raise Refusal("unsupported array dimension expression")
    def variable(name):
        if name in needed:return
        if name in visiting:raise Refusal("cyclic array-dimension variable")
        if variables[name].get('ambiguous'):raise Refusal(f'array-dimension variable {name} has ambiguous declarations')
        visiting.add(name)
        # Refuse every second assignment, including a possible later branch.
        assignments=variable_assignment_count(definition['body'],name)
        if assignments!=1:raise Refusal(f"array-dimension variable {name} is reassigned or ambiguous")
        expression(variables[name]['expression'])
        visiting.remove(name);needed.add(name)
    for port in ports:
        for dim in port['dimensions']:expression(dim)
    return [f"    var {name} = {text_of(variables[name]['expression'])};" for name in sorted(needed,key=lambda n:variables[n]['position'])]


def exact_leaf_counts(definition, ports, variables, arguments):
    """Count dimensions only in a bounded, exact arithmetic subset; never guess."""
    environment={};active=set()
    def evaluate(node):
        if isinstance(node,ast.Constant) and type(node.value) is int:return node.value
        if isinstance(node,ast.List):return [evaluate(x) for x in node.elts]
        if isinstance(node,ast.Name):
            if node.id in environment:return environment[node.id]
            if node.id in variables and node.id not in active:
                if variables[node.id].get('ambiguous') or variable_assignment_count(definition['body'],node.id)!=1:raise ValueError('mutable dimension variable')
                active.add(node.id)
                value=parse(text_of(variables[node.id]['expression']))
                active.remove(node.id);environment[node.id]=value;return value
            raise ValueError('unknown dimension value')
        if isinstance(node,ast.Subscript):
            value=evaluate(node.value);index=evaluate(node.slice)
            if not isinstance(value,list) or type(index)is not int or index<0:raise ValueError('unsupported dimension index')
            return value[index]
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value=evaluate(node.operand)
            if type(value)is not int:raise ValueError('non-scalar dimension operand')
            return value if isinstance(node.op,ast.UAdd) else -value
        if isinstance(node,ast.BinOp):
            a,b=evaluate(node.left),evaluate(node.right)
            if type(a)is not int or type(b)is not int:raise ValueError('non-scalar dimension operand')
            if isinstance(node.op,ast.Add):value=a+b
            elif isinstance(node.op,ast.Sub):value=a-b
            elif isinstance(node.op,ast.Mult):value=a*b
            elif isinstance(node.op,ast.Div) and b and a%b==0:value=a//b
            else:raise ValueError('unsupported exact dimension arithmetic')
            if abs(value)>=2**127:raise ValueError('dimension arithmetic exceeds exact subset')
            return value
        raise ValueError('unsupported dimension expression')
    def parse(text):
        if len(text)>10000:raise ValueError('dimension expression too long')
        return evaluate(ast.parse(text,mode='eval').body)
    try:
        for name,argument in zip(definition['parameters'],arguments):environment[name]=parse(argument)
    except (ValueError,SyntaxError,IndexError,RecursionError):return {p['name']:None for p in ports}
    result={}
    for port in ports:
        try:
            size=1
            for expression in port['dimensions']:
                dimension=parse(text_of(expression))
                if type(dimension)is not int or dimension<0 or dimension>1000000:raise ValueError('dimension out of bound')
                size*=dimension
                if size>10000000:raise ValueError('leaf count exceeds prototype bound')
            result[port['name']]=size
        except (ValueError,SyntaxError,IndexError,RecursionError):result[port['name']]=None
    return result


def render_prototype(source_path, source, template, arguments, sources, parent_sources=None):
    matches=[d for d in definitions(source) if d['name']==template]
    if len(matches)!=1:raise Refusal("target template is missing or ambiguous")
    definition=matches[0]
    if len(arguments)!=len(definition['parameters']):raise Refusal("concrete template parameter count differs")
    ports,variables=inspect_ports(definition)
    reads=access_evidence(definition,ports,source_path)
    writes=parent_write_evidence(template,ports,sources if parent_sources is None else parent_sources)
    leaf_counts=exact_leaf_counts(definition,ports,variables,arguments)
    attached=[{'input':p['name'],'dimensions':[text_of(d) for d in p['dimensions']],
               'tags':[{'name':tag,'value':None,'value_status':'presence_only_no_value_attached'} for tag in p['tags']],
               'source_file':str(source_path),'source_line':p['line'],'scalar_leaves':leaf_counts[p['name']],'enforcement':'attached_without_enforcement'}
              for p in ports if p['direction']=='input' and p['tags']]
    info={'original_template':template,'original_template_line':definition['line'],
          'tag_declarations':attached,'target_tag_accesses':reads,'candidate_parent_tag_writes':writes,
          'classification':{'tagged_input_declarations':len(attached),'tagged_input_scalar_leaves':sum(x['scalar_leaves'] for x in attached) if all(x['scalar_leaves'] is not None for x in attached) else None,'presence_only_in_recorded_sources':bool(attached) and not reads and not writes,'presence_only_globally':None,'parent_write_search_coverage':'recorded prepared-source closure only; caller completeness is unknown','tag_read_in_target':any(x['kind']=='target_tag_read' for x in reads),'tag_write_in_target':any(x['kind']=='target_tag_write' for x in reads),'parent_writes_value':bool(writes)}}
    legacy=legacy_wrapper(source_path,template,arguments)
    if not attached:return legacy,[],info
    if reads or writes:
        info['generation_refusal']='tag value cannot be reproduced exactly from an isolated fragment; target access or candidate caller write requires a proven concrete value'
        return None,[],info
    try:
        lines=dimension_declarations(definition,ports,variables,sources)
        bridge='__S_TagBridge_'+sha((str(source_path)+'::'+template).encode())[:16]
        existing={t.text for s in sources.values() for t in tokenize(s) if IDENT.fullmatch(t.text)}
        if bridge in existing:raise Refusal("generated bridge template name collides with project source")
        names={p['name'] for p in ports}
        if '__s_tag_target' in names or any(f'__s_tag_input_{i}' in names for i in range(len(ports))):raise Refusal("generated bridge signal name collision")
        include=str(source_path).replace('\\','/').replace('"','\\"')
        result=[f'pragma circom 2.1.6;','','include "'+include+'";','',f'template {bridge}({", ".join(definition["parameters"])}) {{',*lines]
        for p in ports:
            dims=''.join('['+text_of(d)+']' for d in p['dimensions'])
            result.append(f'    signal {p["direction"]} {p["name"]}{dims};')
        result.append(f'    component __s_tag_target = {template}({", ".join(definition["parameters"])});')
        for number,p in enumerate(ports):
            if p['direction']!='input':continue
            suffix=''.join('['+text_of(d)+']' for d in p['dimensions'])
            intermediate=f'__s_tag_input_{number}'
            if p['tags']:result.append(f'    signal {{{", ".join(p["tags"])}}} {intermediate}{suffix};')
            def wire(level,indices):
                indent='    '*(level+1)
                if level==len(p['dimensions']):
                    access=''.join('['+i+']' for i in indices)
                    if p['tags']:
                        result.append(f'{indent}{intermediate}{access} <== {p["name"]}{access};')
                        result.append(f'{indent}__s_tag_target.{p["name"]}{access} <== {intermediate}{access};')
                    else:result.append(f'{indent}__s_tag_target.{p["name"]}{access} <== {p["name"]}{access};')
                else:
                    index=f'__s_tag_i_{number}_{level}'
                    if index in names or index in definition['parameters'] or index in variables:raise Refusal("generated loop variable name collision")
                    result.append(f'{indent}for (var {index} = 0; {index} < {text_of(p["dimensions"][level])}; {index}++) {{')
                    wire(level+1,indices+[index]);result.append(indent+'}')
            wire(0,[])
        for number,p in enumerate(ports):
            if p['direction']!='output':continue
            def wire_output(level,indices):
                indent='    '*(level+1)
                if level==len(p['dimensions']):
                    access=''.join('['+i+']' for i in indices)
                    result.append(f'{indent}{p["name"]}{access} <== __s_tag_target.{p["name"]}{access};')
                else:
                    index=f'__s_tag_o_{number}_{level}'
                    if index in names or index in definition['parameters'] or index in variables:raise Refusal("generated output loop variable name collision")
                    result.append(f'{indent}for (var {index} = 0; {index} < {text_of(p["dimensions"][level])}; {index}++) {{')
                    wire_output(level+1,indices+[index]);result.append(indent+'}')
            wire_output(0,[])
        result += ['}','',f'component main = {bridge}({", ".join(arguments)});','']
        return '\n'.join(result),attached,info
    except Refusal as error:
        info['generation_refusal']=str(error)
        return None,[],info


class Inputs:
    def __init__(self):self.references={};self.cache={}
    def bytes(self,value,expected=None):
        guard();p=safe(value)
        if p not in self.cache:self.cache[p]=p.read_bytes()
        raw=self.cache[p];digest=sha(raw)
        if expected is not None and digest!=expected:raise Refusal(f'input SHA mismatch: {p}')
        self.references[str(p)]={'path':str(p),'sha256':digest,'bytes':len(raw)}
        return raw
    def json(self,value,expected=None):return json.loads(self.bytes(value,expected))


def write_new(path,value):
    guard();p=safe(path)
    if not p.is_relative_to(OUTPUT_ROOT):raise Refusal('output is outside the fresh prototype folder')
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    with p.open('x') as f:f.write(text)
    return {'path':str(p),'sha256':sha(text.encode()),'bytes':len(text.encode())}


def inventory(args):
    guard();output=safe(args.output)
    if not output.is_relative_to(OUTPUT_ROOT) or output==OUTPUT_ROOT or output.exists():raise Refusal('output must be a fresh subfolder of runs/s-tag-wrapper-2026-10-27')
    inputs=Inputs();measurement=inputs.json(args.measurement);summary=inputs.json(args.prepared_summary)
    compiled=inputs.json(args.compile_summary);selection=inputs.json(args.selection,compiled['selection_input']['sha256'])
    selected_old={(r['unit'],r['label']):r for r in selection['targets']}
    old_results={};t2051=set()
    for row in compiled['all_request_timings']:
        ref=row['result'];r=inputs.json(ref['path'],ref['sha256']);key=(r['unit'],r['label']);old_results[key]=r
        if not r['compile_success'] and 'T2051' in (r.get('compiler_error') or ''):t2051.add(key)
    prepared_refs={u['unit_id']:u['prepared_report'] for u in summary['units'] if u['unit_id'] in UNITS}
    inventory_rows=[];planned=[];unit_counts=[];selected_keys=set();untagged_checks=[]
    output.mkdir(parents=True);(output/'wrappers').mkdir()
    for measured in measurement['units']:
        unit=measured['unit']
        if unit not in UNITS:continue
        details=inputs.json(measured['output'],measured['sha256'])
        prepared=inputs.json(prepared_refs[unit]['path'],prepared_refs[unit]['sha256'])
        by_label={r['definition']['label']:r for r in prepared['targets']}
        detail_by_label={r['label']:r for r in details['targets']}
        unit_parent_sources={}
        project_root=safe(prepared['targets'][0]['definition']['project_root'])
        for target_record in prepared['targets']:
            for fp in target_record['source_fingerprints']:
                path=safe(fp['path'])
                if path.suffix=='.circom' and path.is_relative_to(project_root):
                    raw=inputs.bytes(path,fp['sha256'])
                    if path not in unit_parent_sources:unit_parent_sources[path]=raw.decode()
        if set(by_label)!=set(detail_by_label):raise Refusal('prepared/measurement labels differ')
        chosen={label for label,d in detail_by_label.items() if (unit,label) in t2051 or d['template'] in REQUIRED}
        counts=Counter()
        for label,d in detail_by_label.items():
            if not d['inspection_eligible'] and label not in chosen:continue
            guard();old=by_label[label];definition=old['definition'];wrapper=inputs.bytes(definition['entrypoint'],d['existing_wrapper_sha256']).decode()
            row={'unit':unit,'label':label,'original_target_id':old['target_id'],'round2_target_id':d.get('target_id'),
                 'template':definition['template_name'],'concrete_parameters':definition['concrete_parameters'],
                 'inspection_eligible':d['inspection_eligible'],'inspection_complete':d['inspection_eligible'],'selected_for_compile':label in chosen,
                 'round2_fragment_spec_sha256':d.get('fragment_spec_sha256'),'original_wrapper_path':definition['entrypoint'],
                 'original_wrapper_sha256':sha(wrapper.encode()),'original_definition':definition,'definition':definition,
                 'old_compile_success':old_results.get((unit,label),{}).get('compile_success'),
                 'generation_status':'refused','generation_reason':None,'attached_without_enforcement':[],'tag_inventory_status':'unknown'}
            try:
                source_path,template,arguments=original_call(wrapper)
                if template!=definition['template_name']:raise Refusal('wrapper/manifest template differs')
                sources={}
                for fp in old['source_fingerprints']:
                    path=safe(fp['path']);raw=inputs.bytes(path,fp['sha256'])
                    if path.suffix=='.circom' and path!=safe(definition['entrypoint']):sources[path]=raw.decode()
                if source_path not in sources:raise Refusal('target defining source missing from recorded fingerprint closure')
                row['defining_source_file']=str(source_path)
                rendered,attached,info=render_prototype(source_path,sources[source_path],template,arguments,sources,unit_parent_sources)
                row.update(info);row['tag_inventory_status']='classified';row['attached_without_enforcement']=attached
                if rendered is None:raise Refusal(info['generation_refusal'])
                is_tagged=bool(info['tag_declarations']);row['generation_status']='tagged_bridge' if is_tagged else 'unchanged'
                row['rendered_wrapper_sha256']=sha(rendered.encode())
                if not is_tagged:
                    identical=rendered==wrapper
                    untagged_checks.append({'unit':unit,'label':label,'inspection_eligible':d['inspection_eligible'],'byte_identical':identical})
                    if not identical:raise Refusal('untagged wrapper differs from the exact legacy renderer')
                if label in chosen:
                    folder=output/'wrappers'/f'{unit}-{label[:16]}'
                    folder.mkdir()
                    row['wrapper']=write_new(folder/'target.circom',rendered)
                    spec={'original_target_id':old['target_id'],'round2_target_id':d.get('target_id'),'original_fragment_spec_sha256':d.get('fragment_spec_sha256'),
                          'original_definition':definition,'original_wrapper_sha256':row['original_wrapper_sha256'],
                          'prototype_wrapper_sha256':row['wrapper']['sha256'],'attached_without_enforcement':attached,
                          'original_target_tags':info['tag_declarations'],'semantic_change':'No tag-meaning constraints are added; only input/output wire forwarding is introduced.'}
                    row['fragment_spec']=write_new(folder/'fragment-spec.json',spec)
            except (Refusal,ValueError,IndexError,KeyError,UnicodeError) as error:
                row['generation_status']='refused';row['generation_reason']=str(error)
            row['status']='generated' if row.get('wrapper') else 'refused'
            row['wrapper_path']=row.get('wrapper',{}).get('path')
            row['wrapper_sha256']=row.get('wrapper',{}).get('sha256')
            row['reason']=row['generation_reason']
            row['tags_attached_without_enforcement']=row['attached_without_enforcement']
            counts[row['generation_status']]+=1
            inventory_rows.append(row)
            if label in chosen:
                selected_keys.add((unit,label));planned.append(row)
        unit_counts.append({'unit':unit,'inspection_eligible':sum(d['inspection_eligible'] for d in details['targets']),
                            'inventory_targets':sum(r['unit']==unit for r in inventory_rows),'selected_targets':len(chosen),
                            'generation_counts':dict(counts)})
    if set(u['unit'] for u in unit_counts)!=set(UNITS):raise Refusal('both measured units are required')
    if not t2051<=selected_keys:raise Refusal('a recorded T2051 failure was omitted')
    generated=[r for r in planned if r.get('wrapper')]
    refs=sorted(inputs.references.values(),key=lambda r:r['path'])
    inventory_result={'schema_version':1,'kind':'source_tag_inventory','units':unit_counts,'targets':inventory_rows,
                      'input_files':refs,'compile_invocations':0,'judging_invocations':0,'fuzz_invocations':0,
                      'classification_note':'Presence declarations, target .tag reads/writes, and candidate parent value writes can overlap. Parent writes are evidence only and are never assumed to match an isolated concrete instance.',
                      'limitations':['No tag values are guessed. Any observed target tag access or candidate parent value write is refused for bridge generation.',
                                     'Array dimensions retain exact original expressions and immutable local declarations; unsupported dependencies are refused.',
                                     'Prototype generation is not compilation success or completed preparation.']}
    plan={'schema_version':1,'kind':'tag_wrapper_compile_plan','units':unit_counts,'targets':planned,
          'selection_rule':'All round-2 T2051 failures plus every target of the five requested RQ-C template names in both units.',
          'original_t2051_targets':len(t2051),'selected_targets':len(planned),'generated_wrappers':len(generated),
          'refused_targets':len(planned)-len(generated),'compilers':selection['compilers'],'original_selection':compiled['selection_input'],
          'input_files':refs,'compiler_invocations':0,'output_root':str(output)}
    passing_rows=[r for r in inventory_rows if r['inspection_eligible']]
    unknown_rows=[{'unit':r['unit'],'label':r['label'],'reason':r['generation_reason']} for r in passing_rows if r['tag_inventory_status']!='classified']
    expected_untagged={(r['unit'],r['label']) for r in passing_rows if r['tag_inventory_status']=='classified' and not r.get('tag_declarations')}
    checked_untagged={(r['unit'],r['label']) for r in untagged_checks if r['inspection_eligible']}
    preservation={'schema_version':1,'scope':'Round-2 passing cohort: classified untagged wrappers must equal legacy bytes; unknown classifications are reported and prevent a complete preservation claim.',
                  'inspection_passing_cohort':len(passing_rows),'expected_classified_untagged':len(expected_untagged),
                  'checked_classified_untagged':len(checked_untagged),'unknown_classification_count':len(unknown_rows),'unknown_classifications':unknown_rows,
                  'checked':len(untagged_checks),'passed':not unknown_rows and expected_untagged==checked_untagged and all(r['byte_identical'] for r in untagged_checks),'targets':untagged_checks}

    tag_table=[]
    for row in inventory_rows:
        for declaration in row.get('tag_declarations',[]):
            tag_table.append({'unit':row['unit'],'label':row['label'],'template':row['template'],
                              'input':declaration['input'],'dimensions':declaration['dimensions'],'scalar_leaves':declaration['scalar_leaves'],
                              'tags':declaration['tags'],'source_file':declaration['source_file'],'source_line':declaration['source_line'],
                              'classification':row['classification']})
    inventory_result['tagged_input_declarations']=len(tag_table)
    inventory_result['known_tagged_input_scalar_leaves']=sum(r['scalar_leaves'] for r in tag_table if r['scalar_leaves'] is not None)
    inventory_result['unknown_leaf_count_declarations']=sum(r['scalar_leaves'] is None for r in tag_table)
    inventory_result['tagged_targets']=sum(bool(r.get('tag_declarations')) for r in inventory_rows)
    inventory_result['unknown_classification_targets']=sum(r['tag_inventory_status']!='classified' for r in inventory_rows)
    table_ref=write_new(output/'tag-table.json',{'schema_version':1,'rows':tag_table,'count_units':'Declarations and exact scalar leaves are separate; null scalar_leaves means unknown.'})
    inventory_result['tag_table']=table_ref
    outputs=[write_new(output/'inventory.json',inventory_result),write_new(output/'planned.json',plan),write_new(output/'untagged-preservation.json',preservation)]
    print(json.dumps({'outputs':outputs,'selected_targets':len(planned),'generated_wrappers':len(generated),'refused_targets':plan['refused_targets'],'units':unit_counts},ensure_ascii=False))
    if not preservation['passed']:raise SystemExit(2)


def synthetic(args):
    guard();output=safe(args.output)
    if not output.is_relative_to(OUTPUT_ROOT) or output.exists():raise Refusal('synthetic output must be fresh')
    output.mkdir(parents=True)
    # Only the declaration tag differs in the reference target. Neither variant
    # contains a Boolean/range assertion; an out-of-tag-domain input stays legal.
    tagged='pragma circom 2.1.6;\ntemplate Tagged(n) { signal input {binary} x[n]; signal output y[n]; for (var i=0;i<n;i++) { y[i] <== x[i]*x[i] + 7; } }\n'
    reference=tagged.replace('signal input {binary}', 'signal input')
    tagref=write_new(output/'tagged.circom',tagged);plainref=write_new(output/'reference.circom',reference)
    rendered,metadata,_=render_prototype(Path(tagref['path']),tagged,'Tagged',['2'],{Path(tagref['path']):tagged})
    old=write_new(output/'direct-tagged.circom',legacy_wrapper(tagref['path'],'Tagged',['2']))
    baseline=write_new(output/'reference-main.circom',legacy_wrapper(plainref['path'],'Tagged',['2']))
    bridge=write_new(output/'bridge-main.circom',rendered)
    fixture={'schema_version':1,'tagged_source':tagref,'reference_source':plainref,'direct_tagged':old,'reference_main':baseline,'bridge_main':bridge,
             'attached_without_enforcement':metadata,'compiler_options':['--r1cs','--sym','--prime','bn128'],
             'expected_reference_nonlinear_constraints':2,'expected_bridge_nonlinear_constraints':2,
             'comparison':'Compile reference and bridge with the same pinned Circom/settings; compare full normalized R1CS constraints after matching input/output wires by .sym. Extra wire-forwarding equalities may be removed by compiler simplification. A header count alone is not equivalence.',
             'negative_control':'Direct tagged main is expected to fail T2051. The bridge must not add x*(x-1)=0 or any tag-meaning constraint.'}
    print(json.dumps(write_new(output/'fixture-plan.json',fixture)))


def self_test():
    class Tests(unittest.TestCase):
        def render(self,body,args=()):
            source='template T(n) {'+body+'}'
            return render_prototype(Path('/project/t.circom'),source,'T',list(args) or ['2'],{Path('/project/t.circom'):source})
        def test_untagged_exact(self):
            actual,metadata,_=self.render('signal input x[n]; signal output y; y <== x[0];')
            self.assertEqual(actual,legacy_wrapper('/project/t.circom','T',['2']));self.assertEqual(metadata,[])
        def test_bridge_has_no_tag_constraints(self):
            actual,metadata,_=self.render('signal input {binary, uint8} x; signal output y; y <== x*x;')
            self.assertIn('signal input x;',actual);self.assertIn('signal {binary, uint8}',actual)
            self.assertNotIn('===',actual);self.assertNotIn('assert',actual);self.assertNotIn('x*x',actual)
            self.assertEqual(metadata[0]['enforcement'],'attached_without_enforcement')
        def test_arrays_and_outputs(self):
            actual,_,_=self.render('signal input {binary} x[n][2]; signal output y[n][2];')
            self.assertIn('signal input x[n][2];',actual);self.assertIn('signal output y[n][2];',actual)
            self.assertIn('__s_tag_i_0_1',actual);self.assertIn('__s_tag_o_1_1',actual)
        def test_value_read_refused(self):
            actual,metadata,info=self.render('signal input {max} x; signal output y; var k=x.max; y <== x*k;')
            self.assertIsNone(actual);self.assertEqual(metadata,[]);self.assertTrue(info['classification']['tag_read_in_target'])
        def test_parent_value_write_refused(self):
            source='template T(n){signal input {max} x; signal output y; y <== x;} template P(){component c=T(2);c.x.max=8;}'
            actual,_,info=render_prototype(Path('/p.circom'),source,'T',['2'],{Path('/p.circom'):source})
            self.assertIsNone(actual);self.assertTrue(info['classification']['parent_writes_value'])
        def test_no_guess_signal_dimension(self):
            rendered,_,info=self.render('signal input nSignals; signal input {binary} x[nSignals];')
            self.assertIsNone(rendered);self.assertIn('unresolved value',info['generation_refusal'])
        def test_immutable_dimension_expression_copied(self):
            actual,_,_=self.render('var m=n+1; signal input {binary} x[m]; signal output out[m];')
            self.assertIn('var m = n + 1;',actual)
        def test_reassigned_dimension_refused(self):
            rendered,_,info=self.render('var m=n+1; m=3; signal input {binary} x[m];')
            self.assertIsNone(rendered);self.assertIn('reassigned',info['generation_refusal'])
        def test_other_reassignments_refused_with_inventory_evidence(self):
            for change in [r'm \= 2;', '++m;', '--m;', 'm >>= 1;', 'm **= 2;', 'm[0] = 2;']:
                rendered,metadata,info=self.render('var m=4; '+change+' signal input {binary} x[m];')
                self.assertIsNone(rendered,change)
                self.assertEqual(metadata,[])
                self.assertEqual(len(info['tag_declarations']),1)
                self.assertIn('reassigned',info['generation_refusal'])
        def test_source_function_dimension(self):
            source='function Size(n){return n+1;} template T(n){signal input {binary} x[Size(n)];}'
            rendered,_,_=render_prototype(Path('/p.circom'),source,'T',['2'],{Path('/p.circom'):source})
            self.assertIn('x[Size ( n )]',rendered)
        def test_impure_dimension_function_refused(self):
            source='function Size(n){signal a;return n;} template T(n){signal input {binary} x[Size(n)];}'
            rendered,_,info=render_prototype(Path('/p.circom'),source,'T',['2'],{Path('/p.circom'):source})
            self.assertIsNone(rendered);self.assertIn('source-only',info['generation_refusal'])
        def test_comments_do_not_create_tag_access(self):
            rendered,_,info=self.render('signal input {binary} x; // x.binary\n signal output y; y <== x;')
            self.assertIsNotNone(rendered);self.assertEqual(info['target_tag_accesses'],[])
        def test_unrelated_loop_variable_redeclarations_do_not_affect_interface(self):
            body='signal input {binary} x[n]; signal output out[n]; for (var i=0;i<n;i++){out[i] <== x[i];} for (var i=0;i<n;i++){var unused=i;}'
            rendered,metadata,_=self.render(body)
            self.assertIsNotNone(rendered);self.assertEqual(len(metadata),1)
            plain=body.replace('{binary}','')
            rendered,metadata,_=self.render(plain)
            self.assertEqual(rendered,legacy_wrapper('/project/t.circom','T',['2']));self.assertEqual(metadata,[])
        def test_only_needed_ambiguous_locals_are_refused(self):
            rendered,_,_=self.render('var unused=1;var unused=2;signal input {binary} x[n];')
            self.assertIsNotNone(rendered)
            rendered,_,info=self.render('var m=1;var m=2;signal input {binary} x[m];')
            self.assertIsNone(rendered);self.assertIn('ambiguous',info['generation_refusal'])
        def test_multiple_names(self):
            rendered,metadata,_=self.render('signal input {binary} a, b[n]; signal output out;')
            self.assertEqual(len(metadata),2);self.assertIn('signal input b[n];',rendered)
        def test_untagged_serialization_unchanged_renderer(self):
            s=legacy_wrapper('/project/a.circom','T',['[1, 2]','3'])
            path,name,args=original_call(s)
            self.assertEqual(legacy_wrapper(path,name,args),s)
        def test_forbidden_paths(self):
            for p in ['runs/n6-b6h-test/x','runs/n6-a-remeasure-2026-10-25.noindex/state.json','/Volumes/zkfdo-jcache/x']:
                with self.assertRaises(Refusal):safe(p)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    if not result.wasSuccessful():raise SystemExit(1)


def main():
    guard();parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('inventory')
    p.add_argument('--measurement',default='runs/s-inspection-improve-2026-10-27/after/measurement.json')
    p.add_argument('--prepared-summary',default='runs/n6-a1b-2026-10-08/preparation-summary.json')
    p.add_argument('--compile-summary',default='runs/s-inspection-improve-2026-10-27/compile-summary.json')
    p.add_argument('--selection',default='runs/s-inspection-improve-2026-10-27/compile-check/selection.json')
    p.add_argument('--output',required=True)
    p=sub.add_parser('synthetic');p.add_argument('--output',required=True)
    sub.add_parser('self-test');args=parser.parse_args()
    {'inventory':inventory,'synthetic':synthetic,'self-test':lambda _:self_test()}[args.command](args)

if __name__=='__main__':main()
