import os

from flask import Flask
from os.path import dirname
from os.path import join
from os.path import realpath
from . import auth
from . import db
from . import dicom

UPLOAD_FOLDER = join(dirname(realpath(__file__)), 'uploads/..')
RT_SET_FOLDER = join(dirname(realpath(__file__)), 'uploads/sets/..')
CT_IMAGE_FOLDER = join(dirname(realpath(__file__)), 'uploads/scans/..')


def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        DATABASE=os.path.join(app.instance_path, 'flaskr.sqlite'),   
    )
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["RT_SET_FOLDER"] = RT_SET_FOLDER
    app.config["CT_IMAGE_FOLDER"] = CT_IMAGE_FOLDER

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # a simple page that says hello
    @app.route('/hello')
    def hello():
        return 'Hello, World!'

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(dicom.bp)
    app.add_url_rule('/', endpoint='index')

    return app


