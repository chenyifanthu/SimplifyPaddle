import os
import cv2
import copy
import numpy as np

from utils import predict_rec
from utils import predict_det
from utils import predict_structure
from utils import utility
from utils.matcher import distance, compute_iou


def expand(pix, det_box, shape):
    x0, y0, x1, y1 = det_box
    #     print(shape)
    h, w, c = shape
    tmp_x0 = x0 - pix
    tmp_x1 = x1 + pix
    tmp_y0 = y0 - pix
    tmp_y1 = y1 + pix
    x0_ = tmp_x0 if tmp_x0 >= 0 else 0
    x1_ = tmp_x1 if tmp_x1 <= w else w
    y0_ = tmp_y0 if tmp_y0 >= 0 else 0
    y1_ = tmp_y1 if tmp_y1 <= h else h
    return x0_, y0_, x1_, y1_


def sorted_boxes(dt_boxes):
    """
    Sort text boxes in order from top to bottom, left to right
    args:
        dt_boxes(array):detected text boxes with shape [4, 2]
    return:
        sorted boxes(array) with shape [4, 2]
    """
    num_boxes = dt_boxes.shape[0]
    sorted_boxes = sorted(dt_boxes, key=lambda x: (x[0][1], x[0][0]))
    _boxes = list(sorted_boxes)

    for i in range(num_boxes - 1):
        if abs(_boxes[i + 1][0][1] - _boxes[i][0][1]) < 10 and \
                (_boxes[i + 1][0][0] < _boxes[i][0][0]):
            tmp = _boxes[i]
            _boxes[i] = _boxes[i + 1]
            _boxes[i + 1] = tmp
    return _boxes

def to_excel(html_table, excel_path):
    from utils.tablepyxl import tablepyxl
    tablepyxl.document_to_xl(html_table, excel_path)
    
class TableSystem(object):
    def __init__(self, args, text_detector=None, text_recognizer=None):
        self.text_detector = predict_det.TextDetector(args) if text_detector is None else text_detector
        self.text_recognizer = predict_rec.TextRecognizer(args) if text_recognizer is None else text_recognizer
        self.table_structurer = predict_structure.TableStructurer(args)

    def __call__(self, img):
        ori_im = img.copy()
        structure_res, elapse = self.table_structurer(copy.deepcopy(img))
        dt_boxes, elapse = self.text_detector(copy.deepcopy(img))
        dt_boxes = sorted_boxes(dt_boxes)

        r_boxes = []
        for box in dt_boxes:
            x_min = box[:, 0].min() - 1
            x_max = box[:, 0].max() + 1
            y_min = box[:, 1].min() - 1
            y_max = box[:, 1].max() + 1
            box = [x_min, y_min, x_max, y_max]
            r_boxes.append(box)
        dt_boxes = np.array(r_boxes)

        if dt_boxes is None:
            return None, None
        img_crop_list = []

        for i in range(len(dt_boxes)):
            det_box = dt_boxes[i]
            x0, y0, x1, y1 = expand(2, det_box, ori_im.shape)
            text_rect = ori_im[int(y0):int(y1), int(x0):int(x1), :]
            img_crop_list.append(text_rect)
        rec_res, elapse = self.text_recognizer(img_crop_list)

        pred_html, pred = self.rebuild_table(structure_res, dt_boxes, rec_res)
        return pred_html

    def rebuild_table(self, structure_res, dt_boxes, rec_res):
        pred_structures, pred_bboxes = structure_res
        matched_index = self.match_result(dt_boxes, pred_bboxes)
        pred_html, pred = self.get_pred_html(pred_structures, matched_index, rec_res)
        return pred_html, pred

    def match_result(self, dt_boxes, pred_bboxes):
        matched = {}
        for i, gt_box in enumerate(dt_boxes):
            # gt_box = [np.min(gt_box[:, 0]), np.min(gt_box[:, 1]), np.max(gt_box[:, 0]), np.max(gt_box[:, 1])]
            distances = []
            for j, pred_box in enumerate(pred_bboxes):
                distances.append(
                    (distance(gt_box, pred_box), 1. - compute_iou(gt_box, pred_box)))  # 获取两两cell之间的L1距离和 1- IOU
            sorted_distances = distances.copy()
            # 根据距离和IOU挑选最"近"的cell
            sorted_distances = sorted(sorted_distances, key=lambda item: (item[1], item[0]))
            if distances.index(sorted_distances[0]) not in matched.keys():
                matched[distances.index(sorted_distances[0])] = [i]
            else:
                matched[distances.index(sorted_distances[0])].append(i)
        return matched

    def get_pred_html(self, pred_structures, matched_index, ocr_contents):
        end_html = []
        td_index = 0
        for tag in pred_structures:
            if '</td>' in tag:
                if td_index in matched_index.keys():
                    b_with = False
                    if '<b>' in ocr_contents[matched_index[td_index][0]] and len(matched_index[td_index]) > 1:
                        b_with = True
                        end_html.extend('<b>')
                    for i, td_index_index in enumerate(matched_index[td_index]):
                        content = ocr_contents[td_index_index][0]
                        if len(matched_index[td_index]) > 1:
                            if len(content) == 0:
                                continue
                            if content[0] == ' ':
                                content = content[1:]
                            if '<b>' in content:
                                content = content[3:]
                            if '</b>' in content:
                                content = content[:-4]
                            if len(content) == 0:
                                continue
                            if i != len(matched_index[td_index]) - 1 and ' ' != content[-1]:
                                content += ' '
                        end_html.extend(content)
                    if b_with:
                        end_html.extend('</b>')

                end_html.append(tag)
                td_index += 1
            else:
                end_html.append(tag)
        return ''.join(end_html), end_html


if __name__ == '__main__':
    args = utility.parse_args()
    
    args.det_model_dir = "./models/ch_ppocr_server_v2.0_det_infer/"
    args.rec_model_dir = "./models/ch_ppocr_server_v2.0_rec_infer/"
    args.table_model_dir = "./models/en_ppocr_mobile_v2.0_table_structure_infer/"
    args.use_gpu = False
    
    table_system = TableSystem(args)

    in_dir = "./test-imgs/"
    out_dir = "./test-results/"
    for filename in os.listdir(in_dir)[3:]:
        if filename.split('.')[1] in ['JPG', 'jpg', 'png', 'jpeg']:
            infile = in_dir + filename
            outfile = out_dir + filename.split('.')[0] + '.xls'
            print(infile + " -> " + outfile)
            img = cv2.imread(infile)
            pred_html = table_system(img)
            print(pred_html)
            to_excel(pred_html, outfile)

    