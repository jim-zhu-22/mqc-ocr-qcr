"""Page-aware, conservative numbered headings; retain every non-header line."""
import re

HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:[.．、:：]\s*|\s+)([^\d].*)$")
SUBHEADING = re.compile(r"^\s*(\d+(?:\.\d+)+)\s*[.．、:：]?\s*([^\d\s].*)$")
PAGE = re.compile(r"^(?:页\s*[:：]?\s*\d+\s*/\s*\d+|第\s*\d+\s*页(?:\s*共\s*\d+\s*页)?|Page\s+\d+\s+of\s+\d+)$", re.I)


def split_sections(pages):
    sections, removed = [], []
    current = None
    last_top = 0
    for page in pages:
        number = page["page_num"]
        page_lines = page["text_content"].splitlines()
        # Only a page label in the first eight lines can delimit a header prefix.
        # Keep it in OCR and in removed_lines, without attaching it to the prior section.
        header_end = next((i for i, line in enumerate(page_lines[:8], 1) if PAGE.fullmatch(line.strip())), 0)
        for line_no, raw in enumerate(page_lines, 1):
            line = raw.strip()
            if not line:
                continue
            if PAGE.fullmatch(line) or line_no <= header_end:
                removed.append({"page": number, "line": line_no, "text": line, "reason": "header prefix ending in anchored page label" if line_no <= header_end else "anchored page label"})
                continue
            match = SUBHEADING.match(line) or HEADING.match(line)
            if match:
                sid, title = match.groups()
                title = title.strip()
                top = int(sid.split(".")[0])
                # Reject list items that restart inside sections, long sentences and tables.
                plausible = len(title) <= 60 and not re.search(r"[。；;|\t]", title)
                plausible &= ("." in sid and top == last_top) or ("." not in sid and top == last_top + 1)
                if plausible:
                    current = {"section": sid, "title": title, "content": "", "pages": [number], "lines": []}
                    sections.append(current)
                    last_top = top
                    continue
            if current is None:
                current = {"section": "front", "title": "前置信息", "content": "", "pages": [number], "lines": []}
                sections.append(current)
            current["content"] += ("\n" if current["content"] else "") + line
            if number not in current["pages"]:
                current["pages"].append(number)
            current["lines"].append({"page": number, "line": line_no, "text": line})
    return {"sections": sections, "removed_lines": removed, "parser_version": "numbered-conservative-v1", "review_note": "非连续编号或无编号标题保留在正文；规则仍可引用front或所属章节，支持人工校订。"}
