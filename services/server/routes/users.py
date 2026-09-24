"""Signing in, and what a user may change about themselves."""

from flask import Blueprint, request
from flask_cors import cross_origin
from auth import verify_token
from context import mongo
from service.user_service import Role, UserService


bp = Blueprint("users", __name__)


@bp.route("/login", methods=["POST"])
@cross_origin()
def login():
    db = mongo["RMN"]
    return UserService.login(request, db)


@bp.route("/signup", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN, check_username=False)  # the form's username is the new user
def signup(user_id):
    db = mongo["RMN"]
    return UserService.signup(request, db)


@bp.route("/updateSaveVerifiedImages", methods=["PUT"])
@cross_origin()
@verify_token()
def update_user(user_id):
    db = mongo["RMN"]
    return UserService.update_save_verified_images(user_id, request, db)


@bp.route("/updateMoodleStructureInd", methods=["PUT"])
@cross_origin()
@verify_token()
def update_moodle_structure_ind(user_id):
    db = mongo["RMN"]
    return UserService.update_moodle_structure_ind(user_id, request, db)


@bp.route("/password", methods=["POST"])
@cross_origin()
@verify_token()
def change_password(user_id):
    db = mongo["RMN"]
    return UserService.change_password(request, db, True, username=user_id)
