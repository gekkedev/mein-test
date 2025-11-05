import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF


BULLET_CHARS: tuple = (
    "\uf0a3",  # original dingbat
    "□",        # white square
    "◻",
    "▢",
    "☐",
    "▪",
    "■",
    "•",
)
PAGE_LABEL_PREFIX = "Seite "


def build_line_text(span: dict) -> str:
    if "text" in span and span["text"]:
        return span["text"]
    return "".join(char.get("c", "") for char in span.get("chars", []))


def split_inline_options(text: str) -> List[str]:
    stripped = text.strip()
    if not stripped:
        return []

    for bullet in BULLET_CHARS:
        if bullet in stripped and not stripped.startswith(bullet):
            parts = stripped.split(bullet)
            segments: List[str] = []
            head = parts.pop(0).strip()
            if head:
                segments.append(head)
            for option in parts:
                option_text = option.strip()
                if option_text:
                    segments.append(f"{bullet}{option_text}")
            if segments:
                return segments

    return [stripped]


def starts_with_bullet(text: str) -> Optional[str]:
    for bullet in BULLET_CHARS:
        if text.startswith(bullet):
            return bullet
    return None


def load_document_lines(pdf_path: Path) -> Dict[str, list]:
    doc = fitz.open(pdf_path)
    try:
        lines: List[dict] = []
        images_by_page: Dict[int, List[dict]] = {}

        for page_index, page in enumerate(doc, start=1):
            raw = page.get_text("rawdict")
            page_lines: List[dict] = []
            page_images: List[dict] = []

            for block in raw.get("blocks", []):
                block_type = block.get("type")

                if block_type == 0:  # text block
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        text_parts = [build_line_text(span) for span in spans]
                        text = "".join(text_parts).strip()

                        if not text:
                            continue

                        line_entry = {
                            "text": text,
                            "bbox": tuple(line.get("bbox", (0, 0, 0, 0))),
                            "page": page_index,
                        }
                        page_lines.append(line_entry)

                elif block_type == 1:  # image block
                    image_bytes: Optional[bytes] = block.get("image")
                    if not image_bytes:
                        continue

                    image_entry = {
                        "bbox": tuple(block.get("bbox", (0, 0, 0, 0))),
                        "ext": block.get("ext", "png") or "png",
                        "bytes": image_bytes,
                        "page": page_index,
                    }
                    page_images.append(image_entry)

            page_lines.sort(key=lambda entry: (entry["bbox"][1], entry["bbox"][0]))
            lines.extend(page_lines)
            images_by_page[page_index] = page_images

        return {"lines": lines, "images": images_by_page}
    finally:
        doc.close()


def update_bounds(bounds: dict, page: int, bbox: tuple) -> None:
    entry = bounds.setdefault(
        page,
        {
            "top": bbox[1],
            "bottom": bbox[3],
            "left": bbox[0],
            "right": bbox[2],
        },
    )
    entry["top"] = min(entry["top"], bbox[1])
    entry["bottom"] = max(entry["bottom"], bbox[3])
    entry["left"] = min(entry["left"], bbox[0])
    entry["right"] = max(entry["right"], bbox[2])


def parse_questions(lines: List[dict]):
    questions: List[dict] = []
    current_question: Optional[dict] = None
    current_section = {"part": None, "topic": None}

    for entry in lines:
        raw_text = entry["text"].strip()

        if not raw_text:
            continue

        segments = split_inline_options(raw_text)

        if not segments:
            continue

        for segment in segments:
            text = segment

            if text.startswith(PAGE_LABEL_PREFIX):
                continue

            if text.startswith("Teil "):
                current_section["part"] = text
                continue

            if text.startswith("Allgemeine Fragen") or text.startswith("Bundesland"):
                current_section["topic"] = text
                continue

            if text.startswith("Test") or text.startswith("Aufbau"):
                # ignore document meta sections
                continue

            if text.startswith("Hinweis"):
                continue

            if text.startswith("Aufgabe "):
                if current_question:
                    finalize_question(current_question, questions)

                number_part = text.replace("Aufgabe", "").strip()
                try:
                    question_number = int(number_part)
                except ValueError:
                    question_number = None

                current_question = {
                    "display_number": text,
                    "question_number": question_number,
                    "section": {
                        "part": current_section["part"],
                        "topic": current_section["topic"],
                    },
                    "question_lines": [],
                    "answers": [],
                    "bounds": {},
                    "pages": set(),
                }
                update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
                current_question["pages"].add(entry["page"])
                current_question["state"] = "collect_question"
                continue

            if not current_question:
                continue

            bullet = starts_with_bullet(text)
            if bullet:
                option_text = text[len(bullet):].strip()
                current_question["answers"].append({"text": option_text})
                update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
                current_question["pages"].add(entry["page"])
                current_question["state"] = "collect_answers"
                continue

            if current_question["state"] == "collect_answers" and current_question["answers"]:
                current_question["answers"][-1]["text"] += " " + text
                update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
                current_question["pages"].add(entry["page"])
                continue

            current_question["question_lines"].append(text)
            update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
            current_question["pages"].add(entry["page"])

    if current_question:
        finalize_question(current_question, questions)

    return questions


def finalize_question(current_question: dict, questions: List[dict]) -> None:
    question_text = " ".join(current_question["question_lines"]).strip()
    answers = [{"text": answer["text"].strip()} for answer in current_question["answers"]]
    question_entry = {
        "id": len(questions) + 1,
        "display_number": current_question["display_number"],
        "question_number": current_question["question_number"],
        "section": current_question["section"],
        "question": question_text,
        "answers": answers,
        "pages": sorted(current_question["pages"]),
        "bounds": current_question["bounds"],
        "images": [],
    }
    questions.append(question_entry)


def assign_images(questions: List[dict], images_by_page: Dict[int, List[dict]]) -> None:
    image_claims: Dict[int, set] = defaultdict(set)

    for question in questions:
        for page, bounds in question["bounds"].items():
            page_images = images_by_page.get(page, [])
            q_top = bounds["top"]
            q_bottom = bounds["bottom"]

            for image in page_images:
                image_id = id(image["bytes"])
                if image_id in image_claims[page]:
                    continue

                img_top = image["bbox"][1]
                img_bottom = image["bbox"][3]

                overlap = min(q_bottom, img_bottom) - max(q_top, img_top)
                padding = 12

                if overlap >= -padding:
                    question.setdefault("_images", []).append({
                        "page": page,
                        "ext": image["ext"],
                        "bytes": image["bytes"],
                    })
                    image_claims[page].add(image_id)


def normalize_answer_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return " ".join(raw.split())


def question_signature(entry: dict) -> Optional[tuple]:
    question_text = normalize_answer_text(entry.get("question"))
    answers = [normalize_answer_text(opt.get("text")) for opt in entry.get("answers", [])]

    if not question_text or not answers:
        return None

    if any(not answer for answer in answers):
        return None

    return question_text, tuple(answers)


def apply_existing_correct_answers(questions: List[dict], output_json_path: Path) -> None:
    if not output_json_path.exists():
        return

    try:
        with output_json_path.open("r", encoding="utf-8") as existing_file:
            existing_payload = json.load(existing_file)
    except (json.JSONDecodeError, OSError):
        return

    stored_answers: Dict[tuple, dict] = {}

    for entry in existing_payload.get("questions", []):
        idx = entry.get("correct_answer_index")
        if not isinstance(idx, int):
            continue

        signature = question_signature(entry)

        if not signature:
            continue

        stored_answers[signature] = {
            "index": idx,
            "question_number": entry.get("question_number"),
        }

    if not stored_answers:
        return

    reused = 0
    skipped = 0

    for question in questions:
        signature = question_signature(question)
        if not signature:
            continue

        stored = stored_answers.get(signature)
        if not stored:
            continue

        answers_len = len(signature[1])

        if 0 <= stored["index"] < answers_len:
            question["correct_answer_index"] = stored["index"]
            reused += 1
        else:
            skipped += 1

    if skipped and reused:
        print(f"Skipped {skipped} stored answer(s) that no longer match question text; reused {reused}.")
    elif skipped:
        print(f"Skipped {skipped} stored answer(s) that no longer match question text.")
    elif reused:
        print(f"Reused {reused} stored answer(s) from existing dataset.")


def persist_output(
    questions: List[dict],
    output_json_path: Path,
    images_dir: Path,
    pdf_name: str,
) -> None:
    images_dir.mkdir(parents=True, exist_ok=True)

    for question in questions:
        image_entries = []
        for idx, image in enumerate(question.pop("_images", []), start=1):
            filename = f"question_{question['id']:04d}_{idx}.{image['ext']}"
            output_path = images_dir / filename
            with output_path.open("wb") as image_file:
                image_file.write(image["bytes"])

            rel_path = os.path.relpath(output_path, start=output_json_path.parent)
            image_entries.append(Path(rel_path).as_posix())

        question["images"] = image_entries

        # remove internal-only keys
        question.pop("bounds", None)

    payload = {
        "meta": {
            "source": pdf_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "question_count": len(questions),
        },
        "questions": questions,
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with output_json_path.open("w", encoding="utf-8") as json_file:
        json.dump(payload, json_file, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Einbürgerungstest PDF into JSON dataset")
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF source file")
    parser.add_argument(
        "--out-json",
        type=Path,
        default=Path("data/questions.json"),
        help="Destination JSON file path",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=Path("data/images"),
        help="Directory for extracted question images",
    )

    args = parser.parse_args()

    pdf_path: Path = args.pdf_path
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    document = load_document_lines(pdf_path)
    questions = parse_questions(document["lines"])
    assign_images(questions, document["images"])
    apply_existing_correct_answers(questions, args.out_json)
    persist_output(questions, args.out_json, args.images_dir, pdf_path.name)

    print(f"Extracted {len(questions)} questions to {args.out_json}")


if __name__ == "__main__":
    main()
