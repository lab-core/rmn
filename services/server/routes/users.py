"""Signing in, and what a user may change about themselves."""

from flask import Blueprint, json, request
from flask_cors import cross_origin
from auth import request_token, verify_token
from context import mongo
from service.user_service import Role, UserService
from utils.responses import Response


bp = Blueprint("users", __name__, url_prefix="/users")


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


@bp.route("/logout", methods=["POST"])
@cross_origin()
@verify_token()
def logout(user_id):
    db = mongo["RMN"]
    return UserService.logout(request_token(request.form), db)


@bp.route("/all", methods=["GET"])
@cross_origin()
@verify_token(Role.ADMIN)
def all_users(user_id):
    db = mongo["RMN"]
    return Response(
        response=json.dumps({"response": UserService.users_with_roles(db)}),
        status=200,
    )


@bp.route("/impersonate", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN, check_username=False)  # the form's username is the user to become
def impersonate(user_id):
    db = mongo["RMN"]
    return UserService.impersonate(
        user_id, request_token(request.form), request.form.get("username"), db
    )


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
