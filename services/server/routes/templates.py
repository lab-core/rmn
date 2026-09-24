"""The exam templates a teacher builds a task from."""

from flask import Blueprint, request
from flask_cors import cross_origin
from auth import verify_token
from context import mongo, storage
from service.template_service import TemplateService


bp = Blueprint("templates", __name__)


@bp.route("/template", methods=["POST"])
@cross_origin()
@verify_token()
def create_template(user_id):
    db = mongo["RMN"]
    return TemplateService.create_user_template(request, db, storage)


@bp.route("/user/template", methods=["POST"])
@cross_origin()
@verify_token()
def get_all_template_info(user_id):
    db = mongo["RMN"]
    return TemplateService.get_all_template_info(request, db)


@bp.route("/template/delete", methods=["POST"])
@cross_origin()
@verify_token()
def delete_template(user_id):
    db = mongo["RMN"]
    return TemplateService.delete_template(user_id, request, db, storage)


@bp.route("/template/info", methods=["POST"])
@cross_origin()
@verify_token()
def get_template_info(user_id):
    db = mongo["RMN"]
    return TemplateService.get_template_info(user_id, request, db)


@bp.route("/template/download", methods=["POST"])
@cross_origin()
@verify_token()
def download_template(user_id):
    db = mongo["RMN"]
    return TemplateService.download_template_file(user_id, request, db, storage)


@bp.route("/template/download/src", methods=["post"])
@cross_origin()
@verify_token()
def download_template_source(user_id):
    db = mongo["RMN"]
    return TemplateService.download_template_source(user_id, request, db)


@bp.route("/template/modify", methods=["POST"])
@cross_origin()
@verify_token()
def modify_template(user_id):
    db = mongo["RMN"]
    return TemplateService.change_template_info(request, db)
