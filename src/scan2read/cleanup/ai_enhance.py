"""Conservative, independently switchable AI cleanup passes.

Works with any AIProvider (OpenAI, Anthropic, Google) from
`cleanup/ai_providers.py`.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import difflib
import json
import logging
import threading
import time

from scan2read.cleanup.ai_cache import cache_key
from scan2read.cleanup.parentheses import tidy_whitespace


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIOptions:
    ocr_words: bool = False
    spacing: bool = False
    anomalies: bool = False
    structure: bool = False
    headings: bool = False
    glosses: bool = False

    def active(self) -> bool:
        return any((self.ocr_words, self.spacing, self.anomalies, self.structure,
                    self.headings, self.glosses))


class AIEnhancer:
    """Apply small validated edits; preserve every original in the audit trail."""

    def __init__(self, provider, options: AIOptions,
                 batch_size: int = 24, budget=None,
                 cache=None, max_parallel: int = 3, progress=None):
        self.provider=provider;self.options=options
        self.batch_size=batch_size
        self.budget=budget
        self.cache=cache
        self.max_parallel=max(1,max_parallel)
        self.progress=progress
        self.audit_records=[];self.usage={"input_tokens":0,"output_tokens":0}
        self.disabled=False
        self._lock=threading.Lock()
        self._total_batches=0;self._completed_batches=0;self._start_time=None

    def _report_progress(self,advance=False):
        """Advance the completed-batch count (if `advance`) and report it.

        Both the mutation and the callback happen inside one lock, so
        concurrent batches finishing at nearly the same moment still report
        in strictly increasing order -- releasing the lock before calling
        back would let two threads race to invoke the callback in whichever
        order the OS happens to schedule them, producing an out-of-order
        (e.g. 2 before 1) progress sequence despite each count being correct
        on its own."""
        with self._lock:
            if advance:
                self._completed_batches+=1
            if self.progress is None:
                return
            completed=self._completed_batches;total=self._total_batches
            elapsed=time.monotonic()-self._start_time if self._start_time else 0.0
            remaining=None
            if completed and total>completed:
                remaining=round(elapsed/completed*(total-completed),1)
            self.progress({"stage":"ai_enhance","completed_batches":completed,"total_batches":total,
                           "elapsed_seconds":round(elapsed,1),"estimated_remaining_seconds":remaining})

    def _build_request(self,batch):
        enabled=[name for name,value in vars(self.options).items() if value]
        items=[{"id":i,"text":record["text"][:1600],"current_kind":record.get("kind","body")}
               for i,record in batch if len(record["text"])<=1600]
        properties={"id":{"type":"integer"}}
        required=["id"]
        if self.options.ocr_words:
            properties["ocr_edits"]={"type":"array","items":{
                    "type":"object","additionalProperties":False,
                    "properties":{"before":{"type":"string"},"after":{"type":"string"},
                                  "confidence":{"type":"number"},"reason":{"type":"string"}},
                    "required":["before","after","confidence","reason"]}}
            required.append("ocr_edits")
        if self.options.spacing:
            properties["spacing_text"]={"type":["string","null"]};required.append("spacing_text")
        if self.options.anomalies:
            properties["anomalies"]={"type":"array","items":{"type":"string"}};required.append("anomalies")
        if self.options.structure:
            properties["kind"]={"type":"string","enum":["unchanged","body","heading","footnote","page_element"]}
            required.append("kind")
        if self.options.headings:
            properties["heading_level"]={"type":"integer","minimum":0,"maximum":3};required.append("heading_level")
        if self.options.glosses:
            properties["remove_glosses"]={"type":"array","items":{"type":"string"}}
            required.append("remove_glosses")
        item_schema={"type":"object","additionalProperties":False,
                     "properties":properties,"required":required}
        schema={"type":"object","additionalProperties":False,
                "properties":{"items":{"type":"array","items":item_schema}},
                "required":["items"]}
        # A real 24-item batch with several genuine spacing corrections needed
        # far more than the old 5000-token ceiling could give it -- the model's
        # response got cut off mid-JSON-string (observed truncation matched a
        # ~5000-token response almost exactly). The 5000 cap was clamping the
        # request's own linear estimate below what it had already calculated
        # was needed, guaranteeing truncation on any sufficiently busy batch.
        # 32000 is a generous sanity ceiling, not the expected typical size.
        output_limit=max(300,min(32000,220*len(items)+(
            sum(len(item["text"].encode("utf-8")) for item in items) if self.options.spacing else 0)))
        instructions=(f"한국어 책 OCR를 보수적으로 검사한다. 활성 기능: {', '.join(enabled)}. "
            "ocr_words가 없으면 ocr_edits는 비운다. spacing이 없으면 spacing_text는 null이다. "
            "anomalies가 없으면 anomalies는 비운다. structure가 없으면 kind=unchanged다. "
            "headings가 없으면 heading_level=0이다. glosses가 없으면 remove_glosses는 비운다. "
            "OCR 수정은 명백한 한두 단어 오류만 제안하고 "
            "문체나 표현을 바꾸지 않는다. spacing_text는 글자를 바꾸지 말고 공백만 고친다 -- "
            "띄어쓰기를 하나도 고칠 필요가 없으면 전체 문장을 다시 쓰지 말고 spacing_text에 "
            "null을 반환한다. remove_glosses는 히브리어/그리스어/라틴어 등 원어 발음을 한글로 "
            "음역해 괄호 등으로 병기한 표현 중, 바로 앞이나 뒤의 한국어 낱말과 같은 뜻이라 "
            "소리 내어 읽으면 같은 말이 반복되는 것처럼 들리는 부분만 골라 원문 그대로(괄호나 "
            "따옴표 등 OCR이 깨뜨렸을 수 있는 기호까지 포함해) 부분 문자열로 담는다. 의미가 "
            "다르거나 처음 나오는 용어 설명, 성경 구절 번호처럼 반복이 아닌 내용은 포함하지 "
            "않는다.")
        input_json=json.dumps(items,ensure_ascii=False)
        return instructions,input_json,schema,output_limit

    @staticmethod
    def _apply_edits(text,edits):
        applied=[]
        for edit in edits:
            before=edit.get("before","");after=edit.get("after","");confidence=edit.get("confidence",0)
            if (not isinstance(confidence,(int,float)) or confidence<.9 or not 1<=len(before)<=30
                    or not 1<=len(after)<=30 or abs(len(before)-len(after))>4 or text.count(before)!=1):
                continue
            candidate=text.replace(before,after,1)
            ratio=difflib.SequenceMatcher(None,text,candidate).ratio()
            if ratio<.96:continue
            text=candidate;applied.append(edit)
        return text,applied

    @staticmethod
    def _apply_glosses(text,spans):
        """Delete AI-identified redundant transliteration glosses (e.g. the
        "(체다카)" in "정의(체다카)"). Unlike _apply_edits this is a pure
        deletion -- there is no "after" text to compare a similarity ratio
        against, since a deletion always scores lower than an equal-sized
        substitution would. The safety net instead is: the span must appear
        exactly once verbatim (the model cannot silently target the wrong
        occurrence or paraphrase), and must be at most a third of the
        paragraph's length -- a gloss is a short aside, not most of the
        sentence."""
        applied=[]
        for span in spans:
            if (not isinstance(span,str) or not 1<=len(span)<=40
                    or len(span)>len(text)/3 or text.count(span)!=1):
                continue
            text=tidy_whitespace(text.replace(span,"",1))
            applied.append(span)
        return text,applied

    def _apply_item(self,record,item):
        """Apply one validated response item to a copy of `record`; return the audit fields."""
        before=record["text"];text=before;applied=[]
        if self.options.ocr_words:text,applied=self._apply_edits(text,item.get("ocr_edits",[]))
        removed_glosses=[]
        if self.options.glosses:text,removed_glosses=self._apply_glosses(text,item.get("remove_glosses",[]))
        spacing=item.get("spacing_text")
        # null/missing spacing_text means "no spacing change" -- the short-result
        # form the model uses instead of echoing back the whole paragraph.
        if self.options.spacing and isinstance(spacing,str) and "".join(spacing.split())=="".join(text.split()):
            text=spacing
        kind=record.get("kind","body")
        if self.options.structure and item.get("kind","unchanged")!="unchanged":kind=item["kind"]
        if self.options.headings and item.get("heading_level",0)>0:kind="heading"
        heading_level=item.get("heading_level",0) if self.options.headings else 0
        record["text"]=text;record["kind"]=kind;record["heading_level"]=heading_level
        return {"before":before,"after":text,"applied_edits":applied,
                "anomalies":item.get("anomalies",[]) if self.options.anomalies else [],
                "kind":kind,"heading_level":heading_level,"removed_glosses":removed_glosses}

    def _call_batch(self,to_call,features):
        """Send exactly one batch's worth of not-yet-cached items. Safe to run
        concurrently with other calls of this method: only touches the
        disjoint set of `record` dicts in `to_call`, and every access to
        shared state (audit_records, usage, cache, budget) is itself
        thread-safe."""
        try:
            if self.disabled:
                with self._lock:
                    self.audit_records.extend({"index":i,"source":"fallback"} for i,_ in to_call)
                return
            try:
                instructions,input_json,schema,max_output_tokens=self._build_request(to_call)
                reserved=0.0
                if self.budget is not None:
                    reserved=self.budget.reserve(instructions+input_json,max_output_tokens,features)
                    if reserved is None:
                        self.disabled=True
                        logger.warning("AI cost limit reached; skipping remaining AI cleanup")
                        with self._lock:
                            self.audit_records.extend({"index":i,"source":"fallback","error":"cost_limit"}
                                                      for i,_ in to_call)
                        return
                response=self.provider.complete(instructions,input_json,schema,max_output_tokens)
                if self.budget is not None:
                    self.budget.record(response.input_tokens,response.output_tokens,
                                        response.cached_input_tokens,features,reserved=reserved)
                returned={item["id"]:item for item in json.loads(response.text)["items"]}
                if set(returned)!={i for i,_ in to_call}:raise ValueError("AI enhancement IDs did not match")
                with self._lock:
                    self.usage["input_tokens"]+=response.input_tokens
                    self.usage["output_tokens"]+=response.output_tokens
                    for i,record in to_call:
                        item=returned[i]
                        fields=self._apply_item(record,item)
                        self.audit_records.append({"index":i,"source":"ai",**fields})
                        if self.cache:
                            self.cache.set(cache_key(self.provider.model,tuple(features),fields["before"]),item)
            except OSError as exc:
                # A connection/HTTP-level failure (OSError's family, including
                # urllib's HTTPError/URLError) means the service itself is
                # unreachable or erroring -- likely to keep failing, so stop
                # sending new batches for the rest of this book.
                logger.warning("AI enhancement connection failed; disabling remaining AI cleanup: %s",exc)
                self.disabled=True
                with self._lock:
                    self.audit_records.extend({"index":i,"source":"fallback","error":type(exc).__name__}
                                              for i,_ in to_call)
            except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
                # The request reached the service fine; this specific response
                # just didn't parse or validate (e.g. truncated at the output
                # ceiling, or a one-off malformed reply). That says nothing
                # about whether the *next* batch will succeed, so only this
                # batch falls back -- a single bad response must not silently
                # disable AI cleanup for the rest of a long book.
                logger.warning("AI enhancement response invalid for this batch; keeping local text: %s",exc)
                with self._lock:
                    self.audit_records.extend({"index":i,"source":"fallback","error":type(exc).__name__}
                                              for i,_ in to_call)
        finally:
            self._report_progress(advance=True)

    def enhance(self,records):
        result=[dict(record) for record in records]
        indexed=[(i,r) for i,r in enumerate(result) if r.get("text")]
        features=[name for name,value in vars(self.options).items() if value]
        batches=[]
        for start in range(0,len(indexed),self.batch_size):
            batch=indexed[start:start+self.batch_size]
            sendable=[pair for pair in batch if len(pair[1]["text"])<=1600]
            if not sendable:continue
            to_call=[]
            for i,record in sendable:
                key=self.cache and cache_key(self.provider.model,tuple(features),record["text"])
                cached=self.cache.get(key) if key else None
                if cached is not None:
                    fields=self._apply_item(record,cached)
                    self.audit_records.append({"index":i,"source":"cache",**fields})
                else:
                    to_call.append((i,record))
            if to_call:batches.append(to_call)
        # Cache lookups above are sequential (cheap, local); only the actual
        # API calls run concurrently, up to max_parallel at a time. A pool
        # naturally caps concurrency regardless of how many batches are
        # submitted, and _call_batch checks self.disabled at the start of
        # each run, so a failure stops *new* work without cancelling
        # requests already in flight.
        if batches:
            self._total_batches=len(batches);self._completed_batches=0
            self._start_time=time.monotonic()
            self._report_progress()
            with ThreadPoolExecutor(max_workers=min(self.max_parallel,len(batches))) as executor:
                list(executor.map(lambda to_call:self._call_batch(to_call,features),batches))
        self.audit_records.append({"summary":{"model":self.provider.model,"usage":self.usage,
                                               "options":vars(self.options)}})
        return result
