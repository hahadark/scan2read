import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from scan2read.cleanup.ai_cache import AIResultCache
from scan2read.cleanup.ai_enhance import AIOptions, AIEnhancer
from scan2read.cleanup.ai_providers import OpenAIProvider
from scan2read.cleanup.ai_usage import AICostBudget


def response(items,input_tokens=100,output_tokens=20):
    return {"output":[{"type":"message","content":[{"type":"output_text",
        "text":json.dumps({"items":items},ensure_ascii=False)}]}],
        "usage":{"input_tokens":input_tokens,"output_tokens":output_tokens}}


def provider(transport, model="gpt-5.6-luna"):
    return OpenAIProvider("secret", model=model, transport=transport)


class AIEnhanceTests(unittest.TestCase):
    def test_cost_limit_skips_api_and_preserves_local_text(self):
        calls=[]
        enhancer=AIEnhancer(provider(lambda payload:calls.append(payload)),AIOptions(spacing=True),
            budget=AICostBudget(0))
        result=enhancer.enhance([{"text":"원문 보존","kind":"body"}])
        self.assertEqual(result[0]["text"],"원문 보존");self.assertEqual(calls,[])
        self.assertEqual(enhancer.audit_records[0]["error"],"cost_limit")
    def test_features_apply_independently_with_conservative_validation(self):
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier,"ocr_edits":[{"before":"엔 키","after":"엔키",
                "confidence":.96,"reason":"고유명사"}],"spacing_text":"엔키의 의미",
                "anomalies":["원문의 분리 표기"],"kind":"heading","heading_level":2}])
        enhancer=AIEnhancer(provider(transport),AIOptions(True,True,True,True,True))
        result=enhancer.enhance([{"text":"엔 키의 의미","kind":"body"}])
        self.assertEqual(result[0]["text"],"엔키의 의미")
        self.assertEqual(result[0]["kind"],"heading")
        self.assertEqual(result[0]["heading_level"],2)
        self.assertEqual(enhancer.usage,{"input_tokens":100,"output_tokens":20})
        self.assertEqual(enhancer.audit_records[0]["anomalies"],["원문의 분리 표기"])

    def test_unrequested_or_unsafe_changes_are_rejected(self):
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier,"ocr_edits":[{"before":"원문","after":"완전히 다른 문장",
                "confidence":.99,"reason":"rewrite"}],"spacing_text":"저자가 쓰지 않은 내용",
                "anomalies":["ignored"],"kind":"heading","heading_level":3}])
        enhancer=AIEnhancer(provider(transport),AIOptions(spacing=True))
        result=enhancer.enhance([{"text":"원문 보존","kind":"body"}])
        self.assertEqual(result[0]["text"],"원문 보존")
        self.assertEqual(result[0]["kind"],"body")
        self.assertEqual(enhancer.audit_records[0]["anomalies"],[])

    def test_glosses_removes_a_redundant_transliteration_span(self):
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier,"remove_glosses":["(체다카)"]}])
        enhancer=AIEnhancer(provider(transport),AIOptions(glosses=True))
        result=enhancer.enhance([{"text":"이것이 정의(체다카)의 뜻이다.","kind":"body"}])
        self.assertEqual(result[0]["text"],"이것이 정의의 뜻이다.")
        self.assertEqual(enhancer.audit_records[0]["removed_glosses"],["(체다카)"])

    def test_glosses_rejects_a_span_that_would_erase_most_of_the_paragraph(self):
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier,"remove_glosses":["정의(체다카)의 뜻이다"]}])
        enhancer=AIEnhancer(provider(transport),AIOptions(glosses=True))
        result=enhancer.enhance([{"text":"이것이 정의(체다카)의 뜻이다.","kind":"body"}])
        self.assertEqual(result[0]["text"],"이것이 정의(체다카)의 뜻이다.")
        self.assertEqual(enhancer.audit_records[0]["removed_glosses"],[])

    def test_glosses_rejects_a_span_not_found_verbatim_or_appearing_twice(self):
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier,"remove_glosses":["(없는말)","(체다카)"]}])
        enhancer=AIEnhancer(provider(transport),AIOptions(glosses=True))
        result=enhancer.enhance([{"text":"정의(체다카)와 정의(체다카)는 같다.","kind":"body"}])
        # "(체다카)" appears twice -- ambiguous which one was meant, so neither span applies.
        self.assertEqual(result[0]["text"],"정의(체다카)와 정의(체다카)는 같다.")
        self.assertEqual(enhancer.audit_records[0]["removed_glosses"],[])

    def test_second_identical_paragraph_reuses_cache_with_no_new_call(self):
        calls=[]
        def transport(payload):
            calls.append(payload)
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier,"spacing_text":"원본 문장"}])
        with tempfile.TemporaryDirectory() as directory:
            cache=AIResultCache(Path(directory))
            enhancer=AIEnhancer(provider(transport),AIOptions(spacing=True),cache=cache)
            first=enhancer.enhance([{"text":"원본문장","kind":"body"}])
            self.assertEqual(first[0]["text"],"원본 문장")
            self.assertEqual(len(calls),1)
            second=enhancer.enhance([{"text":"원본문장","kind":"body"}])
            self.assertEqual(second[0]["text"],"원본 문장")
            self.assertEqual(len(calls),1)
            self.assertEqual(enhancer.audit_records[-2]["source"],"cache")

    def test_cache_hit_never_calls_transport_even_across_new_enhancer_instances(self):
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier,"spacing_text":"원본 문장"}])
        with tempfile.TemporaryDirectory() as directory:
            cache=AIResultCache(Path(directory))
            AIEnhancer(provider(transport),AIOptions(spacing=True),cache=cache)\
                .enhance([{"text":"원본문장","kind":"body"}])
            def failing_transport(payload):
                raise AssertionError("should not call the API on a cache hit")
            reused=AIEnhancer(provider(failing_transport),AIOptions(spacing=True),
                cache=cache).enhance([{"text":"원본문장","kind":"body"}])
            self.assertEqual(reused[0]["text"],"원본 문장")

    def test_default_batch_size_is_in_the_recommended_range(self):
        enhancer=AIEnhancer(provider(lambda payload:None),AIOptions())
        self.assertIn(enhancer.batch_size,range(24,33))

    def test_a_malformed_response_only_skips_its_own_batch_not_the_rest_of_the_book(self):
        # Real-book regression: the very first batch got a response with a
        # mismatched item-ID set; the old code permanently disabled AI
        # cleanup for the rest of a 554-page book on that single hiccup.
        calls=[]
        def transport(payload):
            calls.append(payload)
            identifier=json.loads(payload["input"])[0]["id"]
            if len(calls)==1:
                return response([{"id":identifier+999}])  # wrong id -> ValueError
            return response([{"id":identifier}])
        enhancer=AIEnhancer(provider(transport),AIOptions(anomalies=True),batch_size=1)
        records=[{"text":"첫 문장입니다.","kind":"body"},{"text":"둘째 문장입니다.","kind":"body"}]
        result=enhancer.enhance(records)
        self.assertEqual(len(calls),2)  # the second batch was still attempted
        self.assertFalse(enhancer.disabled)
        self.assertEqual(enhancer.audit_records[0]["source"],"fallback")
        self.assertEqual(enhancer.audit_records[1]["source"],"ai")

    def test_a_connection_failure_does_disable_the_rest_of_the_book(self):
        calls=[]
        def transport(payload):
            calls.append(payload)
            raise OSError("network unreachable")
        enhancer=AIEnhancer(provider(transport),AIOptions(anomalies=True),batch_size=1,
                            max_parallel=1)
        records=[{"text":"첫 문장입니다.","kind":"body"},{"text":"둘째 문장입니다.","kind":"body"}]
        enhancer.enhance(records)
        self.assertEqual(len(calls),1)  # the second batch was never attempted
        self.assertTrue(enhancer.disabled)

    def test_max_output_tokens_scales_for_a_realistic_full_size_spacing_batch(self):
        # Real-book regression: a 24-item batch with real spacing corrections
        # needed far more than the old 5000-token ceiling, so the model's
        # response was cut off mid-JSON-string (observed: JSONDecodeError,
        # "Unterminated string"). The declared ceiling must scale with what
        # a full batch could plausibly need, not clamp below its own estimate.
        enhancer=AIEnhancer(provider(lambda payload:None),AIOptions(spacing=True))
        items=[(i,{"text":"문장 "*200,"kind":"body"}) for i in range(24)]
        _instructions,_input_json,_schema,max_output_tokens=enhancer._build_request(items)
        self.assertGreater(max_output_tokens,5000)

    def test_null_spacing_text_is_a_short_no_change_response(self):
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier,"spacing_text":None}])
        enhancer=AIEnhancer(provider(transport),AIOptions(spacing=True))
        result=enhancer.enhance([{"text":"이미괜찮은문장","kind":"body"}])
        self.assertEqual(result[0]["text"],"이미괜찮은문장")

    def test_batches_run_concurrently_up_to_max_parallel(self):
        lock=threading.Lock();state={"current":0,"max_seen":0}
        def transport(payload):
            with lock:
                state["current"]+=1;state["max_seen"]=max(state["max_seen"],state["current"])
            time.sleep(.05)
            identifier=json.loads(payload["input"])[0]["id"]
            with lock:state["current"]-=1
            return response([{"id":identifier}])
        enhancer=AIEnhancer(provider(transport),AIOptions(anomalies=True),
                            batch_size=1,max_parallel=3)
        records=[{"text":f"문장 번호 {i} 입니다.","kind":"body"} for i in range(6)]
        enhancer.enhance(records)
        self.assertGreaterEqual(state["max_seen"],2)
        self.assertLessEqual(state["max_seen"],3)

    def test_parallel_batches_never_exceed_the_shared_cost_limit(self):
        # Each single-item anomalies-only batch reserves ~$0.00075 (conservative
        # estimate against its own max_output_tokens=300 ceiling) but actually
        # costs far less (~$0.00028) -- realistic, since actual usage must stay
        # within the declared max_output_tokens. A limit of $0.0016 leaves room
        # for exactly two of six concurrently-reserved batches.
        def transport(payload):
            time.sleep(.02)
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier}],input_tokens=200,output_tokens=200)
        budget=AICostBudget(0.0016)
        enhancer=AIEnhancer(provider(transport),AIOptions(anomalies=True),
                            budget=budget,batch_size=1,max_parallel=3)
        records=[{"text":f"문장 번호 {i} 입니다.","kind":"body"} for i in range(6)]
        enhancer.enhance(records)
        self.assertLessEqual(budget.cost_usd,0.0016+1e-9)
        self.assertEqual(budget.reserved_usd,0.0)
        self.assertTrue(any(r.get("error")=="cost_limit" for r in enhancer.audit_records))

    def test_progress_reports_zero_of_n_then_counts_up_to_completion(self):
        reports=[]
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier}])
        enhancer=AIEnhancer(provider(transport),AIOptions(anomalies=True),
                            batch_size=1,progress=reports.append)
        records=[{"text":f"문장 번호 {i} 입니다.","kind":"body"} for i in range(3)]
        enhancer.enhance(records)
        self.assertEqual(reports[0],{"stage":"ai_enhance","completed_batches":0,"total_batches":3,
            "elapsed_seconds":reports[0]["elapsed_seconds"],"estimated_remaining_seconds":None})
        self.assertEqual([r["completed_batches"] for r in reports],[0,1,2,3])
        self.assertEqual(reports[-1]["total_batches"],3)
        self.assertEqual(reports[-1]["completed_batches"],reports[-1]["total_batches"])

    def test_no_progress_callback_means_no_overhead_and_no_error(self):
        def transport(payload):
            identifier=json.loads(payload["input"])[0]["id"]
            return response([{"id":identifier}])
        enhancer=AIEnhancer(provider(transport),AIOptions(anomalies=True))
        result=enhancer.enhance([{"text":"평범한 문장입니다.","kind":"body"}])
        self.assertEqual(len(result),1)
