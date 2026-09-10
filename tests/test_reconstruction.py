import unittest
from types import SimpleNamespace
from scan2read.cleanup.context import ContextJoiner
from scan2read.cleanup.reconstruction import reconstruct
from scan2read.ocr.models import OCRPage, OCRBlock


def block(id,text,x,y,right=450,kind="line"):
    return OCRBlock(id,text,(x,y,right,y+20),.9,0,kind)


class ReconstructionTests(unittest.TestCase):
    def test_pdf_text_runs_on_same_visual_line_are_coalesced(self):
        page = OCRPage(1, 1000, 1000, (
            block("text-1", "이", 100, 200, 120),
            block("text-2", "책 은", 145, 200, 205),
            block("text-3", "쉽게", 230, 200, 280),
            block("text-4", ".", 281, 214, 285),
            block("text-5", "다음 줄입니다.", 100, 225, 300),
        ))
        result = reconstruct([page], {})
        self.assertEqual([p.text for p in result], ["이 책 은 쉽게. 다음 줄입니다."])
        self.assertEqual(result[0].sources,
                         [(1, "text-1"), (1, "text-2"), (1, "text-3"),
                          (1, "text-4"), (1, "text-5")])

    def test_distant_text_runs_are_not_joined_as_one_line(self):
        page = OCRPage(1, 1000, 1000, (
            block("text-1", "왼쪽 단", 80, 200, 250),
            block("text-2", "오른쪽 단", 650, 200, 850),
        ))
        self.assertEqual([p.text for p in reconstruct([page], {})], ["왼쪽 단", "오른쪽 단"])

    def test_context_joiner_repairs_only_dependent_boundaries(self):
        page = OCRPage(1, 1000, 1000, (
            block("a", "고대 근동의", 100, 200),
            block("b", "문화를 설명한다.", 130, 260),
            block("c", "새 문단입니다.", 130, 320),
        ))
        result = reconstruct([page], {}, context_join=ContextJoiner())
        self.assertEqual([p.text for p in result], ["고대 근동의 문화를 설명한다.", "새 문단입니다."])

    def test_context_joiner_uses_morphology_without_rewriting_text(self):
        def analyze(text, top_n=1):
            tag = "ETM" if text.endswith("읽을") else "NNG"
            return [([SimpleNamespace(tag=tag)], 0.0)]
        joiner = ContextJoiner(analyze)
        self.assertTrue(joiner("오래 읽을", "책이다."))
        self.assertFalse(joiner("문장이 끝났다.", "다음 문장이다."))
        self.assertFalse(joiner("새 제목", "본문이다."))
        self.assertFalse(joiner("- 옥스포드대학교", "이 책은 읽기 쉽다."))

    def test_page_continuation_and_sources(self):
        pages=[OCRPage(1,1000,1000,(block("a","문장이 이어지는",100,900),)),
               OCRPage(2,1000,1000,(block("b","부분입니다.",100,100),))]
        result=reconstruct(pages,{})
        self.assertEqual([p.text for p in result],["문장이 이어지는 부분입니다."])
        self.assertEqual(result[0].sources,[(1,"a"),(2,"b")])

    def test_terminal_heading_and_blank_page_block_join(self):
        first=OCRPage(1,1000,1000,(block("a","완료.",100,900),))
        second=OCRPage(2,1000,1000,(block("b","새 제목",100,100,kind="heading"),))
        self.assertEqual(len(reconstruct([first,second],{})),2)
        first=OCRPage(1,1000,1000,(block("a","이어지는",100,900),))
        third=OCRPage(3,1000,1000,(block("b","다음",100,100),))
        self.assertEqual(len(reconstruct([first,OCRPage(2,1000,1000,()),third],{})),2)

    def test_indent_list_and_raw_preservation(self):
        p=OCRPage(1,1000,1000,(block("a","첫 줄",100,200),block("b","이어짐",100,225),
              block("c","새 문단",130,250),block("d","1. 항목",100,275)))
        before=p.to_json()
        self.assertEqual([x.text for x in reconstruct([p],{})],["첫 줄 이어짐","새 문단","1. 항목"])
        self.assertEqual(p.to_json(),before)

    def test_isolated_stray_mark_is_dropped_but_short_real_content_survives(self):
        # Real book ("기독교 위험한 사상 1", p.106): OCR noise from a
        # blurred page edge produced a lone "'" with nothing around it to
        # merge into -- must not survive as its own spoken paragraph. A
        # normal-sized roman numeral or digit heading, by contrast, must.
        p = OCRPage(1, 1000, 1200, (
            block("a", "본문 문장입니다.", 100, 200),
            OCRBlock("b", "'", (100, 500, 340, 520), .9, 0, "line"),
            block("c", "IV", 100, 800, right=300),
            block("d", "다음 문단입니다.", 100, 1000),
        ))
        result = [x.text for x in reconstruct([p], {})]
        self.assertEqual(result, ["본문 문장입니다.", "IV", "다음 문단입니다."])
