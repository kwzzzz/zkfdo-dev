#!/usr/bin/env python3
"""Pure contract tests. No compiler, judge, fuzzer, or existing process signals."""
import hashlib,json,unittest,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import s_round4b_postdeadline_20261027 as post
import s_round4b_view_prepare_20261027 as prep
import s_tag_wrapper_prototype_20261027 as prototype

class Checks(unittest.TestCase):
    def test_no_new_candidates_needs_no_j(self):
        with patch.object(post,"document",return_value={"complete":True,"sha256":[]}),patch.object(post,"save") as save,patch.object(post,"run_j") as run:
            post.new_candidates({"old_candidate_inventory":{},"requests":[]},post.monitor.RUNROOT/"unused")
            run.assert_not_called();self.assertEqual(save.call_args[0][1]["requests"],[])
    def test_deadline(self):
        with self.assertRaisesRegex(ValueError,"deadline"):
            post.deadline(datetime(2026,10,28,14,59,59,tzinfo=timezone.utc))
        post.deadline(datetime(2026,10,28,15,tzinfo=timezone.utc))
    def test_order_preserves_budget_and_targets(self):
        def row(i,t,n):return dict(label=i,target_id=i,template=t,defining_source_file="x.circom",eligible=True,constraints=n)
        meta={"targets":[row("a1","A",1),row("a2","A",2),row("b","B",100)]}
        spec=dict(method="split",total_budget_seconds=600,attempt_cap_seconds=30,targets=[{"target_id":i} for i in ("a1","a2","b")])
        new,ids=post.reorder(spec,meta)
        self.assertEqual(ids,["a1","b","a2"]);self.assertEqual(spec["targets"][1]["target_id"],"a2")
        self.assertEqual(new["total_budget_seconds"],600)
        with self.assertRaises(ValueError):post.reorder(dict(spec,method="whole"),meta)
        with self.assertRaises(ValueError):post.reorder(dict(spec,total_budget_seconds=601),meta)
        with self.assertRaises(ValueError):post.reorder(dict(spec,targets=spec["targets"][:1]),meta)
    def test_verdict_comparison_ignores_timing_but_not_reason(self):
        a={"costs":{"seconds":1},"classes":[{"pattern":"x","reason":"same","verdict":"unknown"}]}
        b=dict(a,costs={"seconds":999})
        self.assertEqual(post.verdict(a),post.verdict(b))
        b["classes"]=[dict(a["classes"][0],reason="different")]
        self.assertNotEqual(post.verdict(a),post.verdict(b))
    def test_manifest_denominator_and_protected_paths(self):
        with self.assertRaises(ValueError):post.selected_revisions({"rows":[]})
        for p in [post.ROOT/"target/no-read",post.ROOT/"runs/n6-a-remeasure-2026-10-25.noindex/x",Path("/Volumes/X9 Pro/x")]:
            with self.assertRaises(ValueError):post.path(p)
    def test_prepare_preserves_untagged_and_records_tagged(self):
        root=post.monitor.RUNROOT/"round4b"/("python-fixture-"+uuid.uuid4().hex);root.mkdir()
        def pin(p,data):
            p.write_bytes(data);return {"path":str(p),"sha256":hashlib.sha256(data).hexdigest()}
        for tagged in (False,True):
            source=root/(str(tagged)+".circom")
            data=("pragma circom 2.1.6; template T(n) { signal input "+("{binary} " if tagged else "")+"x[n]; signal output y[n]; for(var i=0;i<n;i++) {y[i]<==x[i]*x[i];} }").encode()
            sr=pin(source,data);wr=pin(root/(str(tagged)+"-old.circom"),prototype.legacy_wrapper(source,"T",["2"]).encode());fr=pin(root/(str(tagged)+".json"),b'{"original":true}\n')
            result=prep.prepare(dict(label="x",template="T",arguments=["2"],source=sr,sources=[sr],original_wrapper=wr,fragment_spec=fr),root/(str(tagged)+"-out"))
            self.assertEqual(result["original_fragment_spec"]["sha256"],fr["sha256"])
            self.assertEqual(bool(result["component_view"]),tagged)
            if not tagged:self.assertEqual(result["wrapper"]["sha256"],wr["sha256"])
            else:
                view=json.loads(Path(result["component_view"]["path"]).read_text())
                self.assertEqual(view["attached_without_enforcement"],[dict(input="x",tag="binary",value=None)])
    def test_new_j_rejects_old_candidate_without_execution(self):
        plan={"old_candidate_inventory":{},"requests":[{"candidate":{"path":"x","sha256":"abc"},"request":{},"S_ledger":{}}]}
        def doc(ref):
            if ref is plan["old_candidate_inventory"]:return {"complete":True,"sha256":["abc"]}
            if ref is plan["requests"][0]["request"]:return {"source_root":str(post.monitor.RUNROOT),"candidate":{"path":"x"}}
            return {"attempts":[{"candidates":[{"sha256":"abc"}]}]}
        with patch.object(post,"document",side_effect=doc),patch.object(post,"ref",return_value=post.monitor.RUNROOT/"x"),patch.object(post,"save") as save,patch.object(post,"run_j") as run:
            post.new_candidates(plan,post.monitor.RUNROOT/"unused")
            run.assert_not_called();self.assertEqual(save.call_args[0][1]["requests"][0]["status"],"old_or_duplicate_skipped")

if __name__=="__main__":unittest.main()
