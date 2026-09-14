from flask import Flask, request, Response, json, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import datetime as dt
import os
import uuid
from enum import Enum
import re

# Login tokens expire after this many days. Enforced twice: a Mongo TTL index
# purges expired tokens in the background (Mongo runs it about once a minute),
# and verify_token() rejects any token older than the TTL in case the index is
# missing (e.g. a database created before it existed). 0 disables expiry.
TOKEN_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "30"))


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

pass_characters = "a-zA-ZÀ-ÿ0-9.@!#%$?_-"
pattern = re.compile("^[{}]+$".format(pass_characters))


class Role(Enum):
    USER = "Utilisateur"
    ADMIN = "Administrateur"

    def available(role):
        return role == Role.USER.value or role == Role.ADMIN.value


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

    def create_token(username, role, database):
        token = str(uuid.uuid4())
        collection = database["tokens"]
        collection.insert_one({
          "token": token,
          "username": username,
          "role": role,
          "creation_time": dt.datetime.now(dt.UTC)
        })
        return token

    def verify_token(token, database, role=None):
        collection = database["tokens"]
        tokenDB = collection.find_one({"token": token})
        if tokenDB is None:
            return False, ""
        if token_expired(tokenDB):
            # the TTL index removes it eventually; do it now so it cannot be
            # retried in the meantime
            collection.delete_one({"_id": tokenDB["_id"]})
            return False, ""
        if role is None:
            return True, tokenDB["username"]
        return tokenDB["role"] == role.value, tokenDB["username"]

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
        if userDB is None :
            return Response(
                response=json.dumps({"response": f"Nom d'utilisateur/Mot de passe invalide"}),
                status=404,
            )
        if check_password_hash(userDB['password'], password):
            token = UserService.create_token(userDB['username'], userDB['role'], database)
            response = {
                    "username": userDB['username'],
                    "role": userDB['role'],
                    "token": token,
                    "saveVerifiedImages": userDB['saveVerifiedImages'],
                    "moodleStructureInd": userDB['moodleStructureInd']
                }

            return Response(
                response=json.dumps({"response": response}),
                status=200
                )

        return Response(
                response=json.dumps({"response": f"Nom d'utilisateur/Mot de passe invalide"}),
                status=404,
            )

    def signup(request, database):
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
                response=json.dumps({"response": f"Error: password not provided."}),
                status=400,
            )

        username = request_form['username']
        password = request_form['password']
        role = request_form['role']

        if pattern.match(password) is None:
            return Response(
                response=json.dumps({"response": f"Error: password contains illegal characters. You can use only those: %s" % pass_characters}),
                status=400,
            )

        if not Role.available(role):
            return Response(
                response=json.dumps({"response": f"Error: role {role} n'existe pas."}),
                status=400,
            )

        collection = database["users"]
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
            "saveVerifiedImages": False,  # "saveVerifiedImages" in request_form,
            "moodleStructureInd": True  # "moodleStructureInd" in request_form
        }
        collection.insert_one(user)

        return Response(
            response=json.dumps({"response": f'Utilisateur Créé'}),
            status=200
        )

    def update_save_verified_images(request, database):
        request_form = request.form
        if "username" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: username not provided."}),
                status=400,
            )
        if "saveVerifiedImages" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: saveVerifiedImages not provided."}),
                status=400,
            )
        username = request_form['username']
        save_verified_images = bool(int(request_form['saveVerifiedImages']))

        collection = database["users"]

        user = { "$set": { 'saveVerifiedImages': save_verified_images } }

        collection.update_one({'username': username}, user)

        return Response(
            response=json.dumps({"response": f'Utilisateur mise-à-jour'}),
        )

    def update_moodle_structure_ind(request, database):
        request_form = request.form
        if "username" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: username not provided."}),
                status=400,
            )
        if "moodleStructureInd" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: moodleStructureInd not provided."}),
                status=400,
            )
        username = request_form['username']
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
        print("Delete user:", username)

    def users(database):
        collection = database["users"]
        users = collection.find()
        return [u['username'] for u in users]

    def change_password(request, database, verify_old_password):
        request_form = request.form
        if "username" not in request_form:
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
        if pattern.match(new_password) is None:
            return Response(
                response=json.dumps({"response": f"Error: new_password contains illegal characters. You can use only those: %s" % pass_characters}),
                status=400,
            )

        username = request_form['username']
        collection = database["users"]

        collection = database["users"]
        userDB = collection.find_one({"username": username})

        if verify_old_password:
            old_password = request_form['old_password']
            if not check_password_hash(userDB['password'], old_password):
                return Response(
                    response=json.dumps({"response": 'Le mot de passe entré est incorrect!'}),
                    status=500
                )

        collection.update_one(
            {
                'username': username
            },
            {
                "$set": {'password': generate_password_hash(new_password)}
            }
        )

        return Response(
                response=json.dumps({"response": 'Le mot de Passe a été modifié!'}),
                status=200
                )
