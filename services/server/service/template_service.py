from flask import Response, json, send_file
from pathlib import Path
from io import FileIO
from PyPDF2 import PdfWriter, PdfReader
from pdf2image import convert_from_path
from werkzeug.utils import secure_filename
import uuid
import os
import json

from utils.box_converter import convert_box_to_dict, convert_box_to_list
from utils.clients import redis_client


TEMP_FOLDER = Path(__file__).resolve().parent.joinpath("temp")

redis = redis_client()

class TemplateService():

    def create_user_template(request, db, storage):
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

        if not os.path.exists(TEMP_FOLDER):
            os.makedirs(TEMP_FOLDER)
        try:
            template_file = request.files.get("template_file")
            template_file_name = secure_filename(template_file.filename)
            temp_template_file_name = str(TEMP_FOLDER.joinpath(template_file_name))
            template_file.save(FileIO(temp_template_file_name, "wb"))

        except Exception as e:
            print(e)
            return Response(response=f"Error: Failed to download files.", status=900)

        response, code = TemplateService.create_template(request.form, temp_template_file_name, db, storage)
        if code == 200:
            response = json.dumps({"response": response})
        return Response(response=response, status=code)

    def create_template(request_form, template_file_name, db, storage, locked=False, dpi=300):

        if "user_id" not in request_form:
            return f"Error: user_id not provided.", 400

        template_name = request_form['template_name'] if "template_name" in request_form else ""
        user_id = str(request_form["user_id"])

        # Define db and collection used
        collection = db["template"]

        template_id = str(uuid.uuid4())

        try:
            # keep only the page needed
            infile = PdfReader(template_file_name, 'rb')
            output = PdfWriter()
            page = int(request_form.get("template_page", '0'))
            output.add_page(infile.pages[page])
            with open(template_file_name, 'wb') as f:
                output.write(f)
            # transform to image
            img = convert_from_path(template_file_name, dpi=dpi, first_page=0, last_page=1)[0]
            img_filepath = template_file_name.rsplit(".", 1)[0] + ".png"
            print("save image to", img_filepath)
            img.save(img_filepath)
            # move png to storage
            template_file_id = os.path.join("template", f'{template_id}.png')
            storage.move_to(img_filepath, template_file_id)

        except Exception as e:
            print(e)
            return f"Error: Failed to upload files to storage.", 500

        template = {
            "user_id": user_id,
            "template_id": template_id,
            "template_name": str(template_name),
            "template_file_id": template_file_id,
            "locked": locked
        }

        if "grade_box" in request_form:
            grade_box = request_form['grade_box']
            if not locked:
                grade_box = convert_box_to_list(json.loads(grade_box))
            template["grade_box"] = grade_box
        if "matricule_box" in request_form:
            matricule_box = request_form['matricule_box']
            if not locked:
                matricule_box = convert_box_to_list(json.loads(matricule_box))
            template["matricule_box"] = matricule_box

        if locked:
            template["src"] = request_form['src']

        try:
            print(template)
            collection.insert_one(template)
        except Exception as e:
            print(e)
            return f"Error: Failed to insert in MongoDB.", 500

        if "grade_box" in request_form or "matricule_box" in request_form:
            redis.lpush("job_queue", json.dumps({"template_id": template_id}))

        temp = {
            "template_id": template_id,
            "template_name": str(template_name)
        }
        return temp, 200

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
        if template is None:
            return Response(response=json.dumps({"error": f"Cannot delete template {template_id}"}), status=400)

        storage.remove(template["template_file_id"])
        if "template_rendered_file_id" in template:
            storage.remove(template["template_rendered_file_id"])
        collection.delete_one({"template_id": template_id})

        return Response(response=json.dumps({"response": "OK"}), status=200)

    def delete_templates(user_id, db, storage):
        collection = db["template"]
        templates = collection.find({"user_id": user_id, "locked": {"$ne": True}})
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

        user_templates = {
            template['template_name']: {
                "template_name": template['template_name'],
                "template_id": template['template_id'],
                "n_questions": template.get('n_questions'),
                "locked": False
            }
            for template in templates
        }

        def_templates = collection.find({"locked": True})
        for template in def_templates:
            src_name = os.path.basename(template['src'])
            if template['template_name'] in user_templates:
                user_templates[template['template_name']]['src_name'] = src_name
            else:
                user_templates[template['template_name']] = {
                    "template_name": template['template_name'],
                    "template_id": template['template_id'],
                    "n_questions": template.get('n_questions'),
                    "locked": True,
                    "src_name": src_name
                }

        user_templates_list = list(sorted(user_templates.values(), key=lambda d: (not d.get('locked'), d['template_name'])))

        return Response(response=json.dumps({"response": user_templates_list}), status=200)

    def get_template_info(request, db):
        request_form = request.form

        if "user_id" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: user_id not provided."}),
                status=400,
            )
        if "template_id" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: template_id not provided."}),
                status=400,
            )

        user_id = request_form["user_id"]
        template_id = str(request_form["template_id"])

        if not os.path.exists(TEMP_FOLDER):
            os.makedirs(TEMP_FOLDER)


        # Define db and collection used

        collection = db["template"]

        template = collection.find_one({"template_id": template_id})
        if template is None:
            return Response(response="Template not found in db.", status=400)

        template_resp = {
            "template_name": template['template_name'],
            "template_id": template['template_id'],
            "matricule_box": convert_box_to_dict(template.get('matricule_box')),
            "grade_box": convert_box_to_dict(template.get('grade_box')),
            "n_questions": template.get('n_questions'),
            "locked": template.get('locked') and template['user_id'] != user_id,
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
        # # convert to image if pdf
        # if spath.endswith(".pdf"):
        #     img = convert_from_path(storage.abs_path(spath), dpi=300, first_page=0, last_page=1)[0]
        #     filepath = filepath.rsplit(".", 1)[0] + ".png"
        #     print("save image to", filepath)
        #     img.save(filepath)
        # else:
        storage.copy_from(spath, filepath)

        file_send = send_file(filepath)

        os.remove(filepath)

        return file_send

    def download_template_source(request, db):
        request_form = request.form

        #
        if "template_id" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: template_id not provided."}),
                status=400,
            )

        template_id = str(request_form["template_id"])
        template = db["template"].find_one({"template_id": template_id})

        if 'src' not in template:
            return Response(
                response=json.dumps({"response": f"Error: source not found."}),
                status=400,
            )

        return send_file(template['src'])

    def change_template_info(request, db):
        request_form = request.form

        required_fields = {"template_id", "template_name", "user_id"}
        if not set(request_form.keys()) >= required_fields:
            return Response(
                response=json.dumps({"response": "Error: Missing value in request form"}),
                status=400,
            )

        user_id = request_form['user_id']
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
            {"template_id": template_id, "user_id": user_id},
            {
                "$set": update_fields
            })

        redis.lpush("job_queue", json.dumps({"template_id": template_id}))

        return Response(response=json.dumps({"response": "OK"}), status=200)

    def add_default_templates(user_id, db, storage):
        from default_templates.config import default_templates

        # get default templates already defined
        collection = db["template"]
        def_templates_docs = {t['template_name']: t for t in collection.find({"locked": True})}
        print("Default templates:", def_templates_docs)

        # check templates to add
        template_added = []
        print("Default templates to add:", default_templates)
        for name, template in default_templates.items():
            name = f"Example: {name}"
            if name in def_templates_docs:
                print('Remove', name)
                temp = def_templates_docs[name]
                storage.remove(temp["template_file_id"])
                if "template_rendered_file_id" in temp:
                    storage.remove(temp["template_rendered_file_id"])
                collection.delete_one({"template_name": name, "locked": True})

            req = {
                'user_id': user_id,
                'template_name': name,
                'src': template['src']
            }
            if template.get('grade_box'):
                req['grade_box'] = template.get('grade_box')
            if template.get('matricule_box'):
                req['matricule_box'] = template.get('matricule_box')

            filename = template['src'].rsplit('.', 1)[0] + ".pdf"

            resp, code = TemplateService.create_template(req, filename, db, storage, True)
            if code != 200:
                return Response(response=resp, status=code)

            template_added.append(resp)

        return Response(response=json.dumps({"response": template_added}), status=200)
