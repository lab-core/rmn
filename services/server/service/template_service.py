from flask import Flask, request, Response, json, send_file
from utils.box_converter import convert_box_to_dict, convert_box_to_list
from utils.clients import redis_client
from pathlib import Path
from io import FileIO
from PyPDF2 import PdfWriter, PdfReader
from pdf2image import convert_from_path
from werkzeug.utils import secure_filename
import uuid
import os
import json


TEMP_FOLDER = Path(__file__).resolve().parent.joinpath("temp")

redis = redis_client()

class TemplateService():
    def create_template(request, db, storage):
        request_form = request.form

        if "user_id" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: user_id not provided."}),
                status=400,
            )

        template_name = request_form['template_name'] if "template_name" in request_form else ""
        print(request.files)

        if not request.files:
            return Response(
                response=json.dumps({"response": f"Error: No file provided."}),
                status=400,
            )

        if "template_file" not in request.files:
            return Response(
                response=json.dumps({"response": f"Error: Template file not provided."}),
                status=400,
            )

        user_id = str(request_form["user_id"])

        if not os.path.exists(TEMP_FOLDER):
            os.makedirs(TEMP_FOLDER)
        try:
            template_file = request.files.get("template_file")
            template_file_name = secure_filename(template_file.filename)
            template_file.save(FileIO(TEMP_FOLDER.joinpath(template_file_name), "wb"))

        except Exception as e:
            print(e)
            return Response(response=f"Error: Failed to download files.", status=900)


        # Define db and collection used
        collection = db["template"]

        template_id = str(uuid.uuid4())

        try:
            file_name = str(TEMP_FOLDER.joinpath(template_file_name))
            # keep only the page needed
            infile = PdfReader(file_name, 'rb')
            output = PdfWriter()
            page = int(request_form.get("template_page", '0'))
            output.add_page(infile.pages[page])
            with open(file_name, 'wb') as f:
                output.write(f)
            # move pdf to storage
            template_file_id = os.path.join("template", f'{template_id}.pdf')
            storage.move_to(file_name, template_file_id)

        except Exception as e:
            print(e)
            return Response(
                response=json.dumps({"response": f"Error: Failed to upload files to storage."}),
                status=500,
            )

        template = {
            "user_id": user_id,
            "template_id": template_id,
            "template_name": str(template_name),
            "template_file_id": template_file_id
        }

        if "grade_box" in request_form:
            grade_box = convert_box_to_list(json.loads(request_form['grade_box']))
            template["grade_box"] = grade_box
        if "matricule_box" in request_form:
            matricule_box = convert_box_to_list(json.loads(request_form['matricule_box']))
            template["matricule_box"] = matricule_box

        try:
            collection.insert_one(template)
        except Exception as e:
            print(e)
            return Response(
                response=json.dumps({"response": f"Error: Failed to insert in MongoDB."}),
                status=500,
            )

        temp = {
            "template_id": template_id,
            "template_name": str(template_name)
        }
        return Response(response=json.dumps({"response": temp}), status=200)

    def delete_template(request, db, storage):
        request_form = request.form

        if "template_id" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: template_id not provided."}),
                status=400,
            )

        template_id = str(request_form["template_id"])
        collection = db["template"]
        template = collection.find_one({"template_id": template_id})
        storage.remove(template["template_file_id"])
        if "template_rendered_file_id" in template:
            storage.remove(template["template_rendered_file_id"])
        collection.delete_one({"template_id": template_id})

        return Response(response=json.dumps({"response": "OK"}), status=200)

    def delete_templates(user_id, db, storage):
        collection = db["template"]
        templates = collection.find({"user_id": user_id})
        for t in templates:
            storage.remove(t["template_file_id"])
            if "template_rendered_file_id" in t:
                storage.remove(t["template_rendered_file_id"])
        collection.delete_many({"user_id": user_id})

    def get_all_template_info(request, db):
        request_form = request.form

        if "user_id" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: user_id not provided."}),
                status=400,
            )


        user_id = str(request_form["user_id"])

        if not os.path.exists(TEMP_FOLDER):
            os.makedirs(TEMP_FOLDER)


        # Define db and collection used

        collection = db["template"]

        templates = collection.find({"user_id": user_id})

        user_templates_list = [
            {
            "template_name": template['template_name'],
            "template_id": template['template_id']
            }
            for template in templates
        ]

        return Response(response=json.dumps({"response": user_templates_list}), status=200)

    def get_template_info(request, db):
        request_form = request.form

        if "template_id" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: template_id not provided."}),
                status=400,
            )


        template_id = str(request_form["template_id"])

        if not os.path.exists(TEMP_FOLDER):
            os.makedirs(TEMP_FOLDER)


        # Define db and collection used

        collection = db["template"]

        template = collection.find_one({"template_id": template_id})

        template_resp = {
            "template_name": template['template_name'],
            "template_id": template['template_id'],
            "matricule_box": convert_box_to_dict(template.get('matricule_box')),
            "grade_box": convert_box_to_dict(template.get('grade_box')),
        }

        return Response(response=json.dumps({"response": template_resp}), status=200)

    def download_template_file(request, db, storage):
        request_form = request.form

        #
        if "template_id" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: template_id not provided."}),
                status=400,
            )

        template_id = str(request_form["template_id"])
        template = db["template"].find_one({"template_id": template_id})
        spath = template.get("template_rendered_file_id", template["template_file_id"])
        print("template file path:", spath)

        # Save file to local
        filepath = str(TEMP_FOLDER.joinpath(template_id))
        # convert to image if pdf
        if spath.endswith(".pdf"):
            img = convert_from_path(storage.abs_path(spath), dpi=300, first_page=0, last_page=1)[0]
            filepath = filepath.rsplit(".", 1)[0] + ".png"
            print("save image to", filepath)
            img.save(filepath)
        else:
            storage.copy_from(spath, filepath)

        file_send = send_file(filepath)

        os.remove(filepath)

        return file_send

    def change_template_info(request, db):
        request_form = request.form

        required_fields = {"template_id", "template_name"}
        if not set(request_form.keys()) >= required_fields:
            return Response(
                response=json.dumps({"response": "Error: Missing value in request form"}),
                status=400,
            )

        template_name = request_form['template_name']
        template_id = str(request_form["template_id"])
        update_fields = {"template_name": template_name}

        if "matricule_box" in request_form:
            matricule_box = convert_box_to_list(json.loads(request_form['matricule_box']))
            update_fields["matricule_box"] = matricule_box

        if "grade_box" in request_form:
            grade_box = convert_box_to_list(json.loads(request_form['grade_box']))
            update_fields["grade_box"] = grade_box

        collection = db["template"]

        collection.update_one(
            {"template_id": template_id},
            {
                "$set": update_fields
            })

        redis.lpush("job_queue", json.dumps({"template_id": template_id}))

        return Response(response=json.dumps({"response": "OK"}), status=200)


