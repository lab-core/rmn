from flask import Flask, request, json, send_file

from utils.responses import Response
from werkzeug.security import generate_password_hash, check_password_hash
import datetime as dt
import os
import uuid
from enum import Enum
import re
import secrets
import string

# Login tokens expire after this many days. Enforced twice: a Mongo TTL index
# purges expired tokens in the background (Mongo runs it about once a minute),
# and verify_token() rejects any token older than the TTL in case the index is
# missing (e.g. a database created before it existed). 0 disables expiry.
TOKEN_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "30"))

# Hash checked when the login names an unknown user, so that request takes
# as long as a wrong password and the response time does not reveal which
# usernames exist. Random per process: it can never match a submitted value.
_UNKNOWN_USER_HASH = generate_password_hash(uuid.uuid4().hex)


def _utc(value):
    """Return a timezone-aware UTC datetime for a value read from Mongo.

    pymongo returns naive datetimes (UTC) unless the client is tz_aware, while
    the tokens are stored with an aware ``now(dt.UTC)``; comparing the two
    raises TypeError, so normalise here.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def token_expired(record, now=None):
    """True if a token record is older than TOKEN_TTL_DAYS (0 => never)."""
    if TOKEN_TTL_DAYS <= 0:
        return False
    created = record.get("creation_time")
    if created is None:
        # legacy token without a timestamp: cannot prove it is fresh
        return True
    now = now or dt.datetime.now(dt.UTC)
    return now - _utc(created) >= dt.timedelta(days=TOKEN_TTL_DAYS)

# Special characters accepted in a password: the classical set (the one
# Bitwarden generates, !@#$%^&*) plus the . ? _ - that were always accepted.
# The regex and the error message are both built from this list.
PASSWORD_SPECIAL_CHARACTERS = "!@#$%^&*.?_-"
pass_characters = "a-zA-ZÀ-ÿ0-9" + re.escape(PASSWORD_SPECIAL_CHARACTERS)
pattern = re.compile("^[{}]+$".format(pass_characters))
# Shortest accepted password, on signup and on both change routes (the admin
# reset included). The webapp's change dialog already asked for 8; the
# server used to accept one character.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 32  # mirrored in the webapp's utils.ts


def password_error(password):
    """The reason a password is refused, or None when it is acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Error: password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Error: password must be at most {MAX_PASSWORD_LENGTH} characters long."
    if pattern.match(password) is None:
        return (
            "Error: password contains illegal characters. You can use letters, digits and "
            + " ".join(PASSWORD_SPECIAL_CHARACTERS)
        )
    return None
# the username names a directory under front_page_temp and is a key everywhere
# else: letters, digits and . _ @ - only, 3 to 64 characters
username_pattern = re.compile(r"^[A-Za-z0-9._@-]{3,64}$")


def _session(userDB, token, impersonated_by=None):
    """What the webapp keeps of a session: the login and impersonate answer."""
    session = {
        "username": userDB['username'],
        "role": userDB['role'],
        "token": token,
        "saveVerifiedImages": userDB.get('saveVerifiedImages', True),
        "moodleStructureInd": userDB.get('moodleStructureInd', True),
        # an impersonated session is never forced: the admin does not choose
        # the user's password
        "mustChangePassword": impersonated_by is None and userDB.get('must_change_password', False),
    }
    if impersonated_by is not None:
        session["impersonatedBy"] = impersonated_by
    return session


def temporary_password():
    """A random password the password rules accept, for a reset."""
    alphabet = string.ascii_letters + string.digits
    characters = [secrets.choice(alphabet) for _ in range(11)]
    characters.append(secrets.choice(PASSWORD_SPECIAL_CHARACTERS))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


class Role(Enum):
    """The roles, lowest first: each one may do what the ones before it do."""
    USER = "Utilisateur"
    # creates accounts and resets the passwords of the accounts it manages
    MANAGER = "Gestionnaire"
    ADMIN = "Administrateur"

    def available(role):
        return Role.rank(role) >= 0

    def rank(role):
        """The place of a role value among the roles, -1 when it is none."""
        order = [r.value for r in Role]
        return order.index(role) if role in order else -1

    def at_least(role, minimum):
        """Whether the role value ``role`` may do what ``minimum`` may."""
        return Role.rank(role) >= Role.rank(minimum.value)


class UserService:
    def ensure_token_expiration(database):
        """Create (or update) the TTL index that purges expired login tokens.

        Idempotent; called once at server start-up. Mongo refuses to change
        ``expireAfterSeconds`` on an existing index, so the index is dropped
        and recreated when TOKEN_TTL_DAYS changed (or expiry was disabled).
        """
        collection = database["tokens"]
        # every token check (server and socketIO handshakes) looks a token up:
        # without this index each one was a collection scan
        collection.create_index([("token", 1)], name="token_lookup")
        name = "creation_time_ttl"
        existing = collection.index_information().get(name)
        if TOKEN_TTL_DAYS <= 0:
            if existing:
                collection.drop_index(name)
            return
        seconds = TOKEN_TTL_DAYS * 24 * 60 * 60
        if existing and existing.get("expireAfterSeconds") != seconds:
            collection.drop_index(name)
        collection.create_index(
            [("creation_time", 1)], name=name, expireAfterSeconds=seconds
        )

    def create_token(username, role, database, impersonated_by=None, must_change_password=False):
        """A new login token for ``username``.

        ``impersonated_by`` names the admin who opened the session in the
        user's place: the token is the user's in every other respect.
        ``must_change_password`` limits the token to changing the password
        (check_token), until change_password lifts it.
        """
        token = str(uuid.uuid4())
        collection = database["tokens"]
        record = {
          "token": token,
          "username": username,
          "role": role,
          "creation_time": dt.datetime.now(dt.UTC)
        }
        if impersonated_by is not None:
            record["impersonated_by"] = impersonated_by
        if must_change_password:
            record["must_change_password"] = True
        collection.insert_one(record)
        return token

    def find_token(token, database):
        """The record of a live login token, None when unknown or expired."""
        collection = database["tokens"]
        tokenDB = collection.find_one({"token": token})
        if tokenDB is None:
            return None
        if token_expired(tokenDB):
            # the TTL index removes it eventually; do it now so it cannot be
            # retried in the meantime
            collection.delete_one({"_id": tokenDB["_id"]})
            return None
        return tokenDB

    def verify_token(token, database, role=None):
        """(valid, username) of a token; ``role`` is the least role it needs."""
        tokenDB = UserService.find_token(token, database)
        if tokenDB is None:
            return False, ""
        if role is None:
            return True, tokenDB["username"]
        return Role.at_least(tokenDB["role"], role), tokenDB["username"]

    def delete_tokens(username, n_days_old, database):
       r = {}
       if username:
           r["username"] = username

       collection = database["tokens"]
       if n_days_old > 0:
           tokens = collection.find(r)
           now = dt.datetime.now(dt.UTC)
           delete_tokens = []
           for t in tokens:
               delta = now - _utc(t["creation_time"])
               if delta.days >= n_days_old:
                   delete_tokens.append(t['token'])
           r["token"] = {"$in": delete_tokens}
           print("Tokens deleted:", len(delete_tokens))
       collection.delete_many(r)

    def login(request, database):
        request_form = request.form
        if "username" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: username not provided."}),
                status=400,
            )

        if "password" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: password not provided."}),
                status=400,
            )
        username = request_form['username']
        password = request_form['password']
        collection = database["users"]
        userDB = collection.find_one({"username": username})
        stored_hash = userDB['password'] if userDB is not None else _UNKNOWN_USER_HASH
        if check_password_hash(stored_hash, password) and userDB is not None:
            token = UserService.create_token(
                userDB['username'], userDB['role'], database,
                must_change_password=userDB.get('must_change_password', False),
            )
            collection.update_one(
                {"_id": userDB["_id"]}, {"$set": {"last_login": dt.datetime.now(dt.UTC)}}
            )
            return Response(
                response=json.dumps({"response": _session(userDB, token)}),
                status=200
                )

        return Response(
                response=json.dumps({"response": f"Nom d'utilisateur/Mot de passe invalide"}),
                status=404,
            )

    def impersonate(admin, admin_token, username, database):
        """Open a session as ``username`` for ``admin``.

        The token is an ordinary one of ``username`` (role included, so an
        admin can be impersonated too): every ownership check of the routes
        holds unchanged. When the admin is already someone else, the session
        stays attributed to the admin who started the chain, and going back to
        that admin gives a plain session.
        """
        if not username:
            return Response(
                response=json.dumps({"response": "Error: username not provided."}),
                status=400,
            )
        userDB = database["users"].find_one({"username": username})
        if userDB is None:
            return Response(
                response=json.dumps({"response": f"Error: user {username} doesn't exist."}),
                status=404,
            )
        tokenDB = database["tokens"].find_one({"token": admin_token}) or {}
        origin = tokenDB.get("impersonated_by", admin)
        impersonated_by = None if origin == username else origin
        print(f"Impersonation: {origin} opens a session as {username}.")
        token = UserService.create_token(
            userDB['username'], userDB['role'], database, impersonated_by
        )
        return Response(
            response=json.dumps({"response": _session(userDB, token, impersonated_by)}),
            status=200
        )

    def logout(token, database):
        """Delete one login token: the webapp drops a borrowed session with it."""
        database["tokens"].delete_one({"token": token})
        return Response(response=json.dumps({"response": "OK"}), status=200)

    def role_of(username, database):
        """The role of a user as stored now, None for an unknown user."""
        userDB = database["users"].find_one({"username": username}, {"role": 1})
        return userDB.get("role") if userDB else None

    def may_manage(manager, userDB, database):
        """Whether ``manager`` may see and reset the account ``userDB``.

        An Administrateur manages everyone; a Gestionnaire only the accounts
        that list them among their managers (the ones they created and the
        ones an admin gave them), never an Administrateur.
        """
        role = UserService.role_of(manager, database)
        if Role.at_least(role, Role.ADMIN):
            return True
        return (
            Role.at_least(role, Role.MANAGER)
            and userDB.get("role") != Role.ADMIN.value
            and manager in userDB.get("managers", [])
        )

    def users_with_roles(database, manager):
        """The users ``manager`` manages, by username, with what the lists show."""
        query = {}
        if not Role.at_least(UserService.role_of(manager, database), Role.ADMIN):
            query = {"managers": manager, "role": {"$ne": Role.ADMIN.value}}
        users = database["users"].find(query)
        tasks = {
            row["_id"]: row["n"]
            for row in database["eval_jobs"].aggregate(
                [{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}]
            )
        }
        return sorted(
            (
                {
                    "username": u["username"],
                    "role": u.get("role"),
                    "managers": u.get("managers", []),
                    "mustChangePassword": u.get("must_change_password", False),
                    "lastLogin": _utc(u["last_login"]).isoformat() if u.get("last_login") else None,
                    "tasks": tasks.get(u["username"], 0),
                }
                for u in users
            ),
            key=lambda u: u["username"].lower(),
        )

    def set_role(admin, username, role, database):
        """Give ``username`` another role; their sessions close (a token keeps
        the role it was opened with). An admin cannot change their own role,
        so the last admin cannot lock everyone out by mistake."""
        if username == admin:
            return Response(
                response=json.dumps({"response": "Error: you cannot change your own role."}),
                status=400,
            )
        if not Role.available(role):
            return Response(
                response=json.dumps({"response": f"Error: role {role} n'existe pas."}),
                status=400,
            )
        result = database["users"].update_one({"username": username or ""}, {"$set": {"role": role}})
        if result.matched_count == 0:
            return Response(
                response=json.dumps({"response": f"Error: user {username} doesn't exist."}),
                status=404,
            )
        UserService.delete_tokens(username, 0, database)
        print(f"Role change: {admin} makes {username} {role}.")
        return Response(response=json.dumps({"response": role}), status=200)

    def reset_password(manager, username, database):
        """Give ``username`` a temporary password, to change at the next login.

        The password is generated and returned once: it is never stored in
        clear. The user's sessions are closed.
        """
        userDB = database["users"].find_one({"username": username or ""})
        if userDB is None or not UserService.may_manage(manager, userDB, database):
            # an account the caller does not manage looks like a missing one
            return Response(
                response=json.dumps({"response": f"Error: user {username} doesn't exist."}),
                status=404,
            )
        password = temporary_password()
        database["users"].update_one(
            {"username": username},
            {"$set": {"password": generate_password_hash(password), "must_change_password": True}},
        )
        UserService.delete_tokens(username, 0, database)
        print(f"Password reset: {manager} resets the password of {username}.")
        return Response(
            response=json.dumps({"response": {"username": username, "password": password}}),
            status=200,
        )

    def set_managers(username, managers, database):
        """Replace the managers of ``username``; each one must be a Gestionnaire."""
        users = database["users"]
        if users.find_one({"username": username or ""}) is None:
            return Response(
                response=json.dumps({"response": f"Error: user {username} doesn't exist."}),
                status=404,
            )
        managers = sorted(set(managers))
        found = {
            u["username"]
            for u in users.find({"username": {"$in": managers}, "role": Role.MANAGER.value})
        }
        refused = [m for m in managers if m not in found]
        if refused:
            return Response(
                response=json.dumps({"response": f"Error: not a Gestionnaire: {', '.join(refused)}."}),
                status=400,
            )
        users.update_one({"username": username}, {"$set": {"managers": managers}})
        return Response(response=json.dumps({"response": managers}), status=200)

    def signup(request, database, creator=None):
        """Create the account the form describes.

        ``creator`` is the user creating it, None on the operator route: a
        Gestionnaire cannot create an Administrateur, and the creator becomes
        the first manager of the account. The new user chooses their own
        password at the first login.
        """
        request_form = request.form
        if "username" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: username not provided."}),
                status=400,
            )

        if "password" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: password not provided."}),
                status=400,
            )

        if "role" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: role not provided."}),
                status=400,
            )

        username = request_form['username']
        password = request_form['password']
        role = request_form['role']

        if username_pattern.match(username) is None:
            return Response(
                response=json.dumps({"response": "Error: username must be 3 to 64 characters among letters, digits and . _ @ -"}),
                status=400,
            )

        error = password_error(password)
        if error is not None:
            return Response(response=json.dumps({"response": error}), status=400)

        if not Role.available(role):
            return Response(
                response=json.dumps({"response": f"Error: role {role} n'existe pas."}),
                status=400,
            )

        collection = database["users"]
        managers = []
        if creator is not None and not Role.at_least(UserService.role_of(creator, database), Role.ADMIN):
            if role == Role.ADMIN.value:
                return Response(
                    response=json.dumps({"response": "Error: only an Administrateur creates an Administrateur."}),
                    status=403,
                )
            # an admin manages everyone already
            managers = [creator]
        isUserExisting = collection.count_documents({"username": username}) > 0
        if isUserExisting :
            return Response(
                response=json.dumps({"response": f"Nom d'utilisateur existant"}),
                status=404,
            )

        hashed_password = generate_password_hash(password)

        user = {
            "username": username,
            "password": hashed_password,
            "role": role,
            # on by default: the digits of a validated copy are what the
            # recogniser is retrained on (process_copy.digit_bank). The
            # profile screen turns it off.
            "saveVerifiedImages": True,
            "moodleStructureInd": True,  # "moodleStructureInd" in request_form
            "managers": managers,
            # the operator route sets a password its owner chose
            "must_change_password": creator is not None,
        }
        collection.insert_one(user)

        return Response(
            response=json.dumps({"response": f'Utilisateur Créé'}),
            status=200
        )

    def update_save_verified_images(username, request, database):
        """Set the saveVerifiedImages flag of ``username`` (the token's owner).

        The form's ``username`` used to be trusted; ``check_token`` now refuses
        a form naming another user and the handlers no longer read it.
        """
        request_form = request.form
        if "saveVerifiedImages" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: saveVerifiedImages not provided."}),
                status=400,
            )
        save_verified_images = bool(int(request_form['saveVerifiedImages']))

        collection = database["users"]

        user = { "$set": { 'saveVerifiedImages': save_verified_images } }

        collection.update_one({'username': username}, user)

        return Response(
            response=json.dumps({"response": f'Utilisateur mise-à-jour'}),
        )

    def update_moodle_structure_ind(username, request, database):
        """Set the moodleStructureInd flag of ``username`` (the token's owner)."""
        request_form = request.form
        if "moodleStructureInd" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: moodleStructureInd not provided."}),
                status=400,
            )
        moodle_structure_ind = bool(int(request_form['moodleStructureInd']))

        collection = database["users"]

        user = { "$set": { 'moodleStructureInd': moodle_structure_ind } }

        collection.update_one({'username': username}, user)

        return Response(
            response=json.dumps({"response": f'Utilisateur mise-à-jour'}),
        )

    def delete(username, database):
        UserService.delete_tokens(username, 0, database)
        collection = database["users"]
        collection.delete_many({'username': username})
        # nobody is managed by a user who is gone
        collection.update_many({'managers': username}, {'$pull': {'managers': username}})
        print("Delete user:", username)

    def users(database):
        collection = database["users"]
        users = collection.find()
        return [u['username'] for u in users]

    def change_password(request, database, verify_old_password, username=None):
        """Change a password. ``username`` is the token's owner on /password;
        the admin route leaves it None and names the user in the form."""
        request_form = request.form
        if username is None and "username" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: username not provided."}),
                status=400,
            )
        if verify_old_password and "old_password" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: old_password not provided."}),
                status=400,
            )
        if "new_password" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: new_password not provided."}),
                status=400,
            )

        new_password = request_form['new_password']
        error = password_error(new_password)
        if error is not None:
            return Response(response=json.dumps({"response": error}), status=400)

        if username is None:
            username = request_form['username']
        collection = database["users"]
        userDB = collection.find_one({"username": username})
        if userDB is None:
            return Response(
                response=json.dumps({"response": f"Error: user {username} not found."}),
                status=404,
            )

        if verify_old_password:
            old_password = request_form['old_password']
            if not check_password_hash(userDB['password'], old_password):
                return Response(
                    response=json.dumps({"response": 'Le mot de passe entré est incorrect!'}),
                    status=500
                )

        if userDB.get('must_change_password') and check_password_hash(userDB['password'], new_password):
            return Response(
                response=json.dumps({"response": "Le nouveau mot de passe doit être différent du mot de passe temporaire."}),
                status=400,
            )

        collection.update_one(
            {
                'username': username
            },
            {
                "$set": {'password': generate_password_hash(new_password), 'must_change_password': False}
            }
        )
        # the sessions opened with the old password are no longer limited
        database["tokens"].update_many({"username": username}, {"$unset": {"must_change_password": ""}})

        return Response(
                response=json.dumps({"response": 'Le mot de passe a été modifié!'}),
                status=200
                )
