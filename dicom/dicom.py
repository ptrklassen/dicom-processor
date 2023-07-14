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


# Populate RT_SETS and PIXAL_DATA variables, sort files to folders
# Return string summary and reader friendly file
def process_file(file, filename):
    # Read files and gather common data points
    ds = dcmread(file)
    study=ds.StudyInstanceUID
    series=ds.SeriesInstanceUID
    patient_id=ds.PatientID
    if hasattr(ds.file_meta, "MediaStorageSOPClassUID") and ds.file_meta.MediaStorageSOPClassUID == CT_IMAGE:
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
        # Check if the post request contains the file part
        if 'file' not in request.files:
                flash('No file part')
                return redirect(request.url)
        flash("Hang in there, this may take a minute!")
        for file in data.getlist('file'):        
            file = file
            count += 1
            # Prevent the user/browser from submitting an empty file without a filename.
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

# Accept ROI contour data and convert to pixel volume
def roi_volume(roi_contours):
    contour_areas_stacked = []
    for contour_data in roi_contours:
        # Remove z values from contour_data
        del contour_data[3 - 1::3]
        scan_contour_area = []
        for x in contour_data:
            i = contour_data.index(x)
            # Perform cumulative polyganal area calculation at each area coordinate 
            if i%2 == 0 and i+3 < len(contour_data):
                # Area = 1/2|(x1y2-x2y1) + (x2y3-x3y2) + ... + (xn-1yn-xnyn-1) + (xny1-x1yn)|
                result = ((contour_data[i] * contour_data[i+3]) - (contour_data[i+2] * contour_data[i+1]))/2
                scan_contour_area.append(result)        
        contour_areas_stacked.append(sum(scan_contour_area))
    return sum(contour_areas_stacked)



# Find the index of the heart ROI and return the pixel volume of the heart
def heart_finder(rt_set):
    structure_set = rt_set.StructureSetROISequence
    for roi in structure_set:
        if roi.ROIName == 'HEART':
            heart_index = structure_set.index(roi)
            if heart_index:
                # Locate the Contour Sequence for the HEART ROI
                contour_set = rt_set.ROIContourSequence[heart_index]
                heart_contours = []
                # Collect contour data from the HEART ROI images
                for contour_sequence in contour_set.ContourSequence:
                    heart_contours.append(contour_sequence.ContourData)
                # Convert contour image's pixel area into pixel volume
                heart_x_y_contours = roi_volume(heart_contours)
                return heart_x_y_contours


# Calculate the number of images used in the combined ROIs
def image_counter(rt_set):
    contour_set = rt_set.ROIContourSequence
    number_of_images = 0
    for contour in contour_set:        
        contour_data = len(contour.ContourSequence)
        number_of_images += contour_data
    all_scans = len(rt_set.ReferencedFrameOfReferenceSequence[0].RTReferencedStudySequence[0].RTReferencedSeriesSequence[0].ContourImageSequence)
    return number_of_images, all_scans


# Multipy heart pixel volume by pixel spacing to aquire volume in cc
def apply_pixel_data_to_heart_volume():
    for set in RT_SETS:
        if len(set["pixel_spacing"]) == 2 and set["heart"]:
            set["heart"] = set["heart"] * set["pixel_spacing"][0] * set["pixel_spacing"][1] * 0.001
        # Reduce heart volume to 2 decimals
        set["heart"] = round(set["heart"], 2)


# Collate pixel_spacing from uploaded image scans and provide it to the RT_SETS
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
