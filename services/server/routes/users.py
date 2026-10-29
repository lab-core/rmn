"""Signing in, and what a user may change about themselves."""

from flask import Blueprint, json, request
from flask_cors import cross_origin
from auth import request_token, verify_token
from context import mongo
from service import operations
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
@verify_token(Role.MANAGER, check_username=False)  # the form's username is the new user
def signup(user_id):
    db = mongo["RMN"]
    return UserService.signup(request, db, creator=user_id)


@bp.route("/logout", methods=["POST"])
@cross_origin()
@verify_token(allow_password_change=True)
def logout(user_id):
    db = mongo["RMN"]
    return UserService.logout(request_token(request.form), db)


@bp.route("/all", methods=["GET"])
@cross_origin()
@verify_token(Role.MANAGER)
def all_users(user_id):
    db = mongo["RMN"]
    return Response(
        response=json.dumps({"response": UserService.users_with_roles(db, user_id)}),
        status=200,
    )


@bp.route("/reset_password", methods=["POST"])
@cross_origin()
@verify_token(Role.MANAGER, check_username=False)  # the form's username is the account reset
def reset_password(user_id):
    db = mongo["RMN"]
    return UserService.reset_password(user_id, request.form.get("username"), db)


@bp.route("/role", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN, check_username=False)  # the form's username is the account changed
def set_role(user_id):
    db = mongo["RMN"]
    return UserService.set_role(user_id, request.form.get("username"), request.form.get("role"), db)


@bp.route("/sessions/close", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN, check_username=False)  # the form's username is the account logged out
def close_sessions(user_id):
    username = request.form.get("username")
    db = mongo["RMN"]
    if not username or db["users"].find_one({"username": username}) is None:
        return Response(
            response=json.dumps({"response": f"Error: user {username} doesn't exist."}),
            status=404,
        )
    UserService.delete_tokens(username, 0, db)
    return Response(response=json.dumps({"response": "OK"}), status=200)


@bp.route("/delete", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN, check_username=False)  # the form's username is the account deleted
def delete_user(user_id):
    username = request.form.get("username")
    if username == user_id:
        return Response(
            response=json.dumps({"response": "Error: you cannot delete your own account."}),
            status=400,
        )
    if not username or mongo["RMN"]["users"].find_one({"username": username}) is None:
        return Response(
            response=json.dumps({"response": f"Error: user {username} doesn't exist."}),
            status=404,
        )
    print(f"Account deletion: {user_id} deletes {username}.")
    return operations.delete_account(username)


@bp.route("/managers", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN, check_username=False)  # the form's username is the managed account
def set_managers(user_id):
    db = mongo["RMN"]
    return UserService.set_managers(
        request.form.get("username"), request.form.getlist("managers"), db
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
@verify_token(allow_password_change=True)
def change_password(user_id):
    db = mongo["RMN"]
    return UserService.change_password(request, db, True, username=user_id)
