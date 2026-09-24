"""Adding a cover page to every copy of an export."""

import json
import os
import shutil
import tempfile
from io import FileIO
from pathlib import Path
from flask import Blueprint, Response, request, send_file
from flask_cors import cross_origin
from werkzeug.utils import secure_filename
from auth import verify_token
from context import ROOT_DIR
from service.front_page_service import FrontPageHandler
from utils.uploads import extract_bounded


bp = Blueprint("frontpage", __name__, url_prefix="/frontpage")


# limits of the moodle zip sent to /frontpage: the archive was extracted with
# no budget (a small zip can inflate to fill the disk)


FRONT_PAGE_TEMP_FOLDER = ROOT_DIR.joinpath("front_page_temp")
LATEX_INPUT_FILE = ROOT_DIR.joinpath("data.tex")


@bp.route("", methods=["POST"])
@cross_origin()
@verify_token()
def front_page(user_id):
    """Add a LaTeX cover page to every copy of a Moodle zip; returns the new zip.

    Needs pdflatex in the image (the published server image has none, so the
    endpoint answers 501 rather than pretending). Everything happens in a
    directory created for this request and removed afterwards: the working
    directory used to be named after the user, so two requests of one user
    shared it and the user name was a path component.
    """
    request_form = request.form

    if "suffix" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: suffix not provided."}),
            status=400,
        )

    if not request.files:
        return Response(
            response=json.dumps({"response": "Error: No files provided."}),
            status=400,
        )

    if "moodle_zip" not in request.files:
        return Response(
            response=json.dumps({"response": "Error: moodle_zip file not provided."}),
            status=400,
        )

    if "latex_front_page" not in request.files:
        return Response(
            response=json.dumps(
                {"response": "Error: latex_front_page file not provided."}
            ),
            status=400,
        )

    if shutil.which(FrontPageHandler.CMD) is None:
        return Response(
            response=json.dumps({"response": "Error: LaTeX (pdflatex) is not installed on the server."}),
            status=501,
        )

    suffix = str(request_form["suffix"])
    moodle_zip = request.files.get("moodle_zip")
    latex_front_page = request.files.get("latex_front_page")

    os.makedirs(FRONT_PAGE_TEMP_FOLDER, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"{secure_filename(user_id) or 'user'}_", dir=FRONT_PAGE_TEMP_FOLDER))
    try:
        # streamed to disk: the zip used to be read whole into memory
        moodle_zip_path = work_dir.joinpath("moodle.zip")
        moodle_zip.save(str(moodle_zip_path))
        content_dir = work_dir.joinpath("moodle")
        content_dir.mkdir()
        error = extract_bounded(moodle_zip_path, content_dir)
        if error:
            return Response(response=json.dumps({"response": error}), status=413)
        moodle_zip_path.unlink()

        latex_front_page_path = work_dir.joinpath(secure_filename(latex_front_page.filename) or "front_page.tex")
        latex_front_page.save(FileIO(latex_front_page_path, "wb"))
        shutil.copy(LATEX_INPUT_FILE, work_dir)
        latex_input_file = work_dir.joinpath("data.tex")

        handler = FrontPageHandler()
        done, failed = handler.addFrontPages(
            str(work_dir), str(content_dir), suffix, str(latex_front_page_path), str(latex_input_file)
        )
        # a failure is reported, not hidden behind a 200 with an incomplete zip
        if failed or not done:
            return Response(
                response=json.dumps({"response": f"Error: {failed} copie(s) sans page couverture, {done} réussie(s)."}),
                status=500,
            )

        archive = shutil.make_archive(str(work_dir.joinpath("moodle")), "zip", content_dir)
        # send_file opens the archive now; the directory can go
        return send_file(archive, download_name="moodle.zip", as_attachment=True)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
