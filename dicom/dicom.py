import os

from flask import Blueprint
from flask import current_app
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from dicom.db import get_db

from pydicom import dcmread
from werkzeug.exceptions import abort
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'dcm'}
CT_IMAGE = "1.2.840.10008.5.1.4.1.1.2"
RT_STRUCTURE_SET = "1.2.840.10008.5.1.4.1.1.481.3"
RT_SETS = []
PIXEL_DATA = []


bp = Blueprint('dicom', __name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def process_rt_structure_set(study, series, patient_id, file):
    # convert the file to binary format
    # file = convertToBinaryData(file)
    try:
        db = get_db()
        db.execute(
            'INSERT INTO rt_structure_set (study, series, patient_id, dicom_file)'
            ' VALUES (?, ?, ?, ?)',
            (study, series, patient_id, file)
        )
        db.commit()
    except db.Error as error:
        # Unique constraint failure is expected and the error is hidden to prevent user confusion
        if str(error) == "UNIQUE constraint failed: rt_structure_set.study":
            pass
        else:
            flash(error)

def process_image_instance(study, series, patient_id, instance, file):
    # convert the file to binary format
    # file = convertToBinaryData(file)
    try:
        db = get_db()
        db.execute(
            'INSERT INTO image_instance (study, series, patient_id, instance, dicom_file)'
            ' VALUES (?, ?, ?, ?, ?)',
            (study, series, patient_id, instance, file)
        )
        db.commit()
    except db.Error as error:
        # Unique constraint failure is expected and the error is hidden to prevent user confusion
        if str(error) == "UNIQUE constraint failed: image_instance.instance":
            pass
        else:
            flash(error)

################################################################
# Function for saving to database
################################################################
# def process_file(file, filename):
#     # read the file and gather the common data points
#     ds = dcmread(file)
#     study=ds.StudyInstanceUID
#     series=ds.SeriesInstanceUID
#     patient_id=ds.PatientID
#     if hasattr(ds.file_meta, "MediaStorageSOPClassUID") and ds.file_meta.MediaStorageSOPClassUID == CT_IMAGE:
#         # image instances are saved with their InstanceNumber
#         instance = ds.InstanceNumber
#         process_image_instance(study=study, series=series, patient_id=patient_id, instance=instance, file=file)        
#         return (f"{filename} is CT Image - Instance: {ds.InstanceNumber}".format(filename=filename), ds)
#     if hasattr(ds.file_meta, "MediaStorageSOPClassUID") and ds.file_meta.MediaStorageSOPClassUID == RT_STRUCTURE_SET:
#         process_rt_structure_set(study=study, series=series, patient_id=patient_id, file=file)
#         return (f"{filename} is RT Structure Set".format(filename=filename), ds)


################################################################
# Function for saving to folders
################################################################
def process_file(file, filename):
    # read the file and gather the common data points
    ds = dcmread(file)
    study=ds.StudyInstanceUID
    series=ds.SeriesInstanceUID
    patient_id=ds.PatientID
    if hasattr(ds.file_meta, "MediaStorageSOPClassUID") and ds.file_meta.MediaStorageSOPClassUID == CT_IMAGE:
        # image instances are saved with their InstanceNumber
        # instance = ds.InstanceNumber
        PIXEL_DATA.append(
            {
                "patient": patient_id,
                "study": study,
                "series": series,
                "pixel_spacing": ds.PixelSpacing,
            }
        )
        file.save(os.path.join(current_app.config['CT_IMAGE_FOLDER'], filename))      
        return (f"{filename} is CT Image - Instance: {ds.InstanceNumber}".format(filename=filename), ds)
    if hasattr(ds.file_meta, "MediaStorageSOPClassUID") and ds.file_meta.MediaStorageSOPClassUID == RT_STRUCTURE_SET:
        file.save(os.path.join(current_app.config['RT_SET_FOLDER'], filename))
        heart_contour = heart_finder(ds)
        images, all_scans = image_counter(ds)
        RT_SETS.append(
            {
                "filename": filename,
                "patient": patient_id,
                "study": study,
                "series": series,
                "file": ds,
                "heart": heart_contour,
                "approved_images": images,
                "all_scans": all_scans,
            }
        )    
        return (f"{filename} is RT Structure Set".format(filename=filename), ds)
    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
    return (f"{filename} is Neither an RT Structure set or a CT image".format(filename=filename), ds)
 

@bp.route('/upload', methods=('GET', 'POST'))
def upload_file():
    if request.method == 'POST':
        data = request.files
        count = 0
        processed_files = []
        # check if the post request contains the file part
        if 'file' not in request.files:
                flash('No file part')
                return redirect(request.url)
        for file in data.getlist('file'):        
            file = file
            count += 1
            # prevent the user/browser from submitting an empty file without a filename.
            if file.filename == '':
                flash('No file selected')
                return redirect(request.url)
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                info, ds_file = process_file(file, filename)                
                if info and ds_file:
                    processed_files.append((info, ds_file.PatientID))
        return render_template('dicom/summary.html', count = count, files = processed_files)    
                
    return render_template('dicom/upload.html')


def heart_volume(heart_contures):
    contour_points = []
    for contour_data in heart_contures:
        del contour_data[3 - 1::3]
        # x_y_contours = []
        area_points = []
        for x in contour_data:
            i = contour_data.index(x)
            if i%2 == 0 and i+3 < len(contour_data):
                result = ((contour_data[i] * contour_data[i+3]) - (contour_data[i+2] * contour_data[i+1]))/2
                area_points.append(result)
        
        contour_points.append(sum(area_points))
    return sum(contour_points)



#find the index of the heart ROI and return the pixel volume of the heart
def heart_finder(rt_set):
    structure_set = rt_set.StructureSetROISequence
    for roi in structure_set:
        if roi.ROIName == 'HEART':
            heart_index = structure_set.index(roi)
            if heart_index:
                contour_set = rt_set.ROIContourSequence[heart_index]
                heart_contours = []
                for contour_sequence in contour_set.ContourSequence:
                    heart_contours.append(contour_sequence.ContourData)
                heart_x_y_contours = heart_volume(heart_contours)
                return heart_x_y_contours


def image_counter(rt_set):
    contour_set = rt_set.ROIContourSequence
    number_of_images = 0
    for contour in contour_set:        
        contour_data = len(contour.ContourSequence)
        number_of_images += contour_data
    all_scans = len(rt_set.ReferencedFrameOfReferenceSequence[0].RTReferencedStudySequence[0].RTReferencedSeriesSequence[0].ContourImageSequence)
    return number_of_images, all_scans


def apply_pixel_data_to_heart_volume():
    for set in RT_SETS:
        if len(set["pixel_spacing"]) == 2 and set["heart"]:
            set["heart"] = set["heart"] * set["pixel_spacing"][0] * set["pixel_spacing"][1] * 0.001


def get_pixel_data():
    for set in RT_SETS:
        set["pixel_spacing"] = []
        for data in PIXEL_DATA:
            if set["patient"] == data["patient"] and set["pixel_spacing"] != data["pixel_spacing"]:
                set["pixel_spacing"] = data["pixel_spacing"]
        

@bp.route('/', methods = ['GET'])
def index():
    get_pixel_data()
    apply_pixel_data_to_heart_volume()
    return render_template('dicom/index.html', rt_sets=RT_SETS)
#     db = get_db()
#     rt_sets = db.execute(
#         'SELECT id, study, series, patient_id'
#         ' FROM rt_structure_set'
#         ' ORDER BY patient_id'
#     ).fetchall()
#     return render_template('dicom/index.html', rt_sets=rt_sets)



# def get_file(id):
#     db = get_db()
#     rt_structure_set = db.execute('SELECT id, dicom_file'
#         ' FROM rt_structure_set' 
#         ' WHERE id = ?', 
#         (id,)
#     ).fetchone()

#     if rt_structure_set is None:
#         abort(404, f"RT Structure Set {id} doesn't exist")

#     return rt_structure_set


@bp.route('/file/<filename>', methods = ['GET'])
def list_file(filename):
    filename = filename
    print(os.path.join(current_app.config['RT_SET_FOLDER'], filename))
    file = dcmread(os.path.join(current_app.config['RT_SET_FOLDER'], filename), force=True)
    print(filename, file)
    # dicom_file = file['dicom_file']
    # file.write(dicom_file)
    # ds = dcmread(dicom_file)

    return render_template('dicom/list_file.html', info=filename, file=file)