# Copyright (c) Opendatalab. All rights reserved.
import copy
import json
import logging
import os
import argparse
from pathlib import Path

logger = logging.getLogger(__name__)

from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, read_fn
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.draw_bbox import draw_layout_bbox, draw_span_bbox
from mineru.utils.enum_class import MakeMode
from mineru.backend.vlm.vlm_analyze import doc_analyze as vlm_doc_analyze
from mineru.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json as pipeline_result_to_middle_json
from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make as vlm_union_make
from mineru.utils.guess_suffix_or_lang import guess_suffix_by_path

def prepare_env(output_dir, pdf_file_name)-> tuple[str, str]:
    """Prepare local storage environment."""
    local_image_dir = os.path.join(output_dir,pdf_file_name, "images")
    local_md_dir = os.path.join(output_dir, pdf_file_name)

    os.makedirs(local_image_dir, exist_ok=True)
    os.makedirs(local_md_dir, exist_ok=True)

    return local_image_dir, local_md_dir


def do_parse(
    output_dir,  # Output directory for storing parsing results
    pdf_file_names: list[str],  # List of PDF file names to be parsed
    pdf_bytes_list: list[bytes],  # List of PDF bytes to be parsed
    p_lang_list: list[str],  # List of languages for each PDF, default is 'ch' (Chinese)
    backend="pipeline",  # The backend for parsing PDF, default is 'pipeline'
    parse_method="auto",  # The method for parsing PDF, default is 'auto'
    formula_enable=True,  # Enable formula parsing
    table_enable=True,  # Enable table parsing
    server_url=None,  # Server URL for vlm-http-client backend
    f_draw_layout_bbox=False,  # Whether to draw layout bounding boxes
    f_draw_span_bbox=False,  # Whether to draw span bounding boxes
    f_dump_md=True,  # Whether to dump markdown files
    f_dump_middle_json=True,  # Whether to dump middle JSON files
    f_dump_model_output=False,  # Whether to dump model output files
    f_dump_orig_pdf=False,  # Whether to dump original PDF files
    f_dump_content_list=False,  # Whether to dump content list files
    f_make_md_mode=MakeMode.MM_MD,  # The mode for making markdown content, default is MM_MD
):
    print(f"Starting document parsing with backend: {backend}, method: {parse_method}")
    print(f"Formula parsing enabled: {formula_enable}, Table parsing enabled: {table_enable}")
    if backend == "pipeline":
        for idx, pdf_bytes in enumerate(pdf_bytes_list):
            pdf_file_name = pdf_file_names[idx]
            _lang = p_lang_list[idx]
            content_md_path = os.path.join(output_dir, pdf_file_name, "content.md")
            if os.path.exists(content_md_path):
                print(f"Skipping {pdf_file_name}: content.md already exists.")
                continue
            print(f"Processing file: {pdf_file_name} with language: {_lang}")
            new_pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(pdf_bytes, 0, None)

            infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = pipeline_doc_analyze(
                [new_pdf_bytes], [_lang], parse_method=parse_method, formula_enable=formula_enable, table_enable=table_enable
            )

            model_list = infer_results[0]
            model_json = copy.deepcopy(model_list)
            local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name)
            image_writer, md_writer = FileBasedDataWriter(local_image_dir), FileBasedDataWriter(local_md_dir)

            images_list = all_image_lists[0]
            pdf_doc = all_pdf_docs[0]
            _lang = lang_list[0]
            _ocr_enable = ocr_enabled_list[0]
            middle_json = pipeline_result_to_middle_json(model_list, images_list, pdf_doc, image_writer, _lang, _ocr_enable, formula_enable)

            pdf_info = middle_json["pdf_info"]

            _process_output(
                pdf_info, new_pdf_bytes, pdf_file_name, local_md_dir, local_image_dir,
                md_writer, f_draw_layout_bbox, f_draw_span_bbox, f_dump_orig_pdf,
                f_dump_md, f_dump_content_list, f_dump_middle_json, f_dump_model_output,
                f_make_md_mode, middle_json, model_json, is_pipeline=True
            )
    else:
        if backend.startswith("vlm-"):
            backend = backend[4:]

        f_draw_span_bbox = False
        parse_method = "vlm"
        for idx, pdf_bytes in enumerate(pdf_bytes_list):
            pdf_file_name = pdf_file_names[idx]
            content_md_path = os.path.join(output_dir, pdf_file_name, "content.md")
            if os.path.exists(content_md_path):
                print(f"Skipping {pdf_file_name}: content.md already exists.")
                continue
            pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(pdf_bytes, 0, None)
            local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name)
            image_writer, md_writer = FileBasedDataWriter(local_image_dir), FileBasedDataWriter(local_md_dir)
            middle_json, infer_result = vlm_doc_analyze(pdf_bytes, image_writer=image_writer, backend=backend, server_url=server_url)

            pdf_info = middle_json["pdf_info"]

            _process_output(
                pdf_info, pdf_bytes, pdf_file_name, local_md_dir, local_image_dir,
                md_writer, f_draw_layout_bbox, f_draw_span_bbox, f_dump_orig_pdf,
                f_dump_md, f_dump_content_list, f_dump_middle_json, f_dump_model_output,
                f_make_md_mode, middle_json, infer_result, is_pipeline=False
            )


def _process_output(
        pdf_info,
        pdf_bytes,
        pdf_file_name,
        local_md_dir,
        local_image_dir,
        md_writer,
        f_draw_layout_bbox,
        f_draw_span_bbox,
        f_dump_orig_pdf,
        f_dump_md,
        f_dump_content_list,
        f_dump_middle_json,
        f_dump_model_output,
        f_make_md_mode,
        middle_json,
        model_output=None,
        is_pipeline=True
):
    """Process output files."""
    if f_draw_layout_bbox:
        draw_layout_bbox(pdf_info, pdf_bytes, local_md_dir, f"layout.pdf")

    if f_draw_span_bbox:
        draw_span_bbox(pdf_info, pdf_bytes, local_md_dir, f"span.pdf")

    if f_dump_orig_pdf:
        md_writer.write(
            f"origin.pdf",
            pdf_bytes,
        )

    image_dir = str(os.path.basename(local_image_dir))

    if f_dump_md:
        make_func = pipeline_union_make if is_pipeline else vlm_union_make
        md_content_str = make_func(pdf_info, f_make_md_mode, image_dir)
        md_writer.write_string(
            "content.md",
            md_content_str,
        )

    if f_dump_content_list:
        make_func = pipeline_union_make if is_pipeline else vlm_union_make
        content_list = make_func(pdf_info, MakeMode.CONTENT_LIST, image_dir)
        md_writer.write_string(
            f"content_list.json",
            json.dumps(content_list, ensure_ascii=False, indent=4),
        )

    if f_dump_middle_json:
        md_writer.write_string(
            f"middle.json",
            json.dumps(middle_json, ensure_ascii=False, indent=4),
        )

    if f_dump_model_output:
        md_writer.write_string(
            f"model.json",
            json.dumps(model_output, ensure_ascii=False, indent=4),
        )

    logger.info(f"local output dir is {local_md_dir}")


def parse_doc(
        path_list: list[Path],
        output_dir,
        lang="ch",
        backend="pipeline",
        method="auto",
        formula_enable=True,
        table_enable=True,
        server_url=None,
        debug=False,
):
    """
        Parameter description:
        path_list: List of document paths to be parsed, can be PDF or image files.
        output_dir: Output directory for storing parsing results.
        lang: Language option, default is 'ch', optional values include['ch', 'ch_server', 'ch_lite', 'en', 'korean', 'japan', 'chinese_cht', 'ta', 'te', 'ka'].
            Input the languages in the pdf (if known) to improve OCR accuracy.  Optional.
            Adapted only for the case where the backend is set to "pipeline"
        backend: the backend for parsing pdf:
            pipeline: More general.
            vlm-transformers: More general.
            vlm-vllm-engine: Faster(engine).
            vlm-http-client: Faster(client).
            without method specified, pipeline will be used by default.
        method: the method for parsing pdf:
            auto: Automatically determine the method based on the file type.
            txt: Use text extraction method.
            ocr: Use OCR method for image-based PDFs.
            Without method specified, 'auto' will be used by default.
            Adapted only for the case where the backend is set to "pipeline".
        server_url: When the backend is `http-client`, you need to specify the server_url, for example:`http://127.0.0.1:30000`
        start_page_id: Start page ID for parsing, default is 0
        end_page_id: End page ID for parsing, default is None (parse all pages until the end of the document)
    """
    for path in path_list:
        file_name = str(Path(path).stem)
        print(f"Reading file: {file_name} from path: {path}")
        try:
            pdf_bytes = read_fn(path)
        except Exception as e:
            logger.error(f"Failed to read file {path}, skipping. Error: {e}")
            continue
        try:
            do_parse(
                output_dir=output_dir,
                pdf_file_names=[file_name],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=[lang],
                backend=backend,
                parse_method=method,
                formula_enable=formula_enable,
                table_enable=table_enable,
                server_url=server_url,
                f_draw_layout_bbox=debug,
                f_draw_span_bbox=debug,
                f_dump_md=True,
                f_dump_middle_json=True,
                f_dump_model_output=debug,
                f_dump_orig_pdf=debug,
                f_dump_content_list=debug
            )
        except Exception as e:
            logger.exception(f"Failed to parse file {path}, skipping. Error: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Parse PDF documents.")
    parser.add_argument(
        "--input_dir",
        type=str,
        required=True,
        help="Directory containing PDF files to parse"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        required=True,
        help="Directory to store parsing results"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="en",
        help="Language option for OCR"
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="pipeline",
        help="Backend for parsing PDF"
    )
    parser.add_argument(
        "--method",
        type=str,
        default="auto",
        help="Method for parsing PDF"
    )

    parser.add_argument(
        "--formula_disable",
        action='store_true',
        help="Disable formula parsing"
    )

    parser.add_argument(
        "--table_disable",
        action='store_true',
        help="Disable table parsing"
    )

    parser.add_argument(
        "--server_url",
        type=str,
        default=None,
        help="Server URL for HTTP client backend"
    )

    parser.add_argument(
        "--debug",
        action='store_true',
        help="Enable debug mode with additional outputs"
    )

    args = parser.parse_args()


    """If models cannot be downloaded due to network issues, set MINERU_MODEL_SOURCE=modelscope to use the mirror without a proxy."""
    # os.environ['MINERU_MODEL_SOURCE'] = "modelscope"

    """Use pipeline mode if your environment does not support VLM"""
    parse_doc(
        path_list=[Path(args.input_dir)/f for f in os.listdir(args.input_dir) if f.lower().endswith('.pdf')],
        output_dir=args.output_dir,
        lang=args.lang,
        backend=args.backend,
        method=args.method,
        formula_enable=not args.formula_disable,
        table_enable=not args.table_disable,
        debug=args.debug,
    )

    """To enable VLM mode, change the backend to 'vlm-xxx'"""
    # parse_doc(doc_path_list, output_dir, backend="vlm-transformers")  # more general.
    # parse_doc(doc_path_list, output_dir, backend="vlm-mlx-engine")  # faster than transformers in macOS 13.5+.
    # parse_doc(doc_path_list, output_dir, backend="vlm-vllm-engine")  # faster(vllm-engine).
    # parse_doc(doc_path_list, output_dir, backend="vlm-lmdeploy-engine")  # faster(lmdeploy-engine).
    # parse_doc(doc_path_list, output_dir, backend="vlm-http-client", server_url="http://127.0.0.1:30000")  # faster(client).