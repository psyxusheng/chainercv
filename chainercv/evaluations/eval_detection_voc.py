from __future__ import division

import numpy as np
import six


def eval_detection_voc(
        bboxes, labels, scores, gt_bboxes, gt_labels,
        gt_difficults=None,
        min_iou=0.5, use_07_metric=False):
    """Calculate detection metrics based on evaluation code of PASCAL VOC.

    This function evaluates recall, precison and average precision with
    respect to a class as well as mean average precision.
    This evaluates predicted bounding boxes obtained from a dataset which
    has :math:`N` images.

    Mean average precision is calculated by taking a mean of average
    precision for all classes which have at least one bounding box
    assigned by prediction or ground truth labels.
    The code is based on the evaluation code used in PASCAL VOC Challenge.

    Args:
        bboxes (list of numpy.ndarray): A list of bounding boxes.
            The index to this list corresponds to the index of the data
            obtained from the base dataset. Length of the list is :math:`N`.
            The element of :obj:`bboxes` is coordinates of bounding
            boxes. This is an array whose shape is :math:`(R, 4)`,
            where :math:`R` corresponds
            to the number of bounding boxes, which may vary among boxes.
            The second axis corresponds to :obj:`x_min, y_min, x_max, y_max`
            of a box.
        labels (list of numpy.ndarray): A list of labels.
            Similar to :obj:`bboxes`, its index corresponds to an
            index for the base dataset. Its length is :math:`N`.
        scores (list of numpy.ndarray): A list of confidence scores for
            predicted bounding boxes. Similar to :obj:`bboxes`,
            its index corresponds to an index for the base dataset.
            Its length is :math:`N`.
        gt_bboxes (list of numpy.ndarray): List of ground truth bounding boxes
            whose length is :math:`N`. An element of :obj:`gt_bboxes` is a
            bounding box whose shape is :math:`(R, 4)`. Note that number of
            bounding boxes in each image does not need to be same as the number
            of corresponding predicted boxes.
        gt_labels (list of numpy.ndarray): List of ground truth labels which
            are organized similarly to :obj:`labels`.
        gt_difficults (list of numpy.ndarray): List of boolean arrays which
            is organized similarly to :obj:`labels`. This tells whether the
            corresponding ground truth bounding box is difficult or not.
            By default, this is :obj:`None`. In that case, this function
            consider all bounding boxes to be not difficult.
        min_iou (float): A prediction is correct if its Intersection over
            Union with the ground truth is above this value.
        use_07_metric (bool): Whether to use Pascal VOC 2007 evaluation metric
            for calculating average precision. The default value is
            :obj:`False`.

    Returns:
        dict:

        This function returns a dictionary whose contents are listed
        below with key, value-type and the description of the value.

        * **map** (*float*): mean Average Prediction.
        * **i (an integer corresponding to class id)** (*dict*): This is a \
            dictionary whose keys are :obj:`precision, recall, ap`, which \
            maps to precision, recall and average precision with respect \
            to the class id **i**.

    """
    if not (len(bboxes) == len(labels) == len(scores)
            == len(gt_bboxes) == len(gt_labels)):
        raise ValueError('Length of list inputs need to be same')

    valid_label = np.union1d(
        np.unique(np.concatenate(labels)),
        np.unique(np.concatenate(gt_labels))).astype(np.int32)
    n_img = len(bboxes)

    # Organize predictions into Dict[l, List[bbox]]
    bboxes_list = {l: [np.zeros((0, 4)) for _ in six.moves.range(n_img)]
                   for l in valid_label}
    scores_list = {l: [np.zeros((0,)) for _ in six.moves.range(n_img)]
                   for l in valid_label}
    for n in six.moves.range(n_img):
        for l in valid_label:
            bboxes_l = []
            scores_l = []
            for r in six.moves.range(bboxes[n].shape[0]):
                if l == labels[n][r]:
                    bboxes_l.append(bboxes[n][r])
                    scores_l.append(scores[n][r])
            if len(bboxes_l) > 0:
                bboxes_list[l][n] = np.stack(bboxes_l)
                scores_list[l][n] = np.stack(scores_l)

    # Organize ground truths into Dict[l, List[bbox]]
    empty_bbox = np.zeros((0, 4), dtype=np.float32)
    empty_label = np.zeros((0,), dtype=np.bool)
    gt_bboxes_list = {l: [empty_bbox for _ in six.moves.range(n_img)]
                      for l in valid_label}
    gt_difficults_list = {l: [empty_label for _ in six.moves.range(n_img)]
                          for l in valid_label}
    for n in six.moves.range(n_img):
        for l in valid_label:
            gt_bboxes_l = []
            gt_difficults_l = []
            for r in six.moves.range(gt_bboxes[n].shape[0]):
                if l == gt_labels[n][r]:
                    gt_bboxes_l.append(gt_bboxes[n][r])
                    if gt_difficults is not None:
                        gt_difficults_l.append(gt_difficults[n][r])
                    else:
                        gt_difficults_l.append(
                            np.array(False, dtype=np.bool))
            if len(gt_bboxes_l) > 0:
                gt_bboxes_list[l][n] = np.stack(gt_bboxes_l)
                gt_difficults_list[l][n] = np.stack(gt_difficults_l)

    # Accumulate recacall, precison and ap
    results = {}
    for l in valid_label:
        rec, prec = _pred_and_rec_cls(
            bboxes_list[l],
            scores_list[l],
            gt_bboxes_list[l],
            gt_difficults_list[l],
            min_iou)
        ap = _voc_ap(rec, prec, use_07_metric=use_07_metric)
        results[l] = {}
        results[l]['recall'] = rec
        results[l]['precision'] = prec
        results[l]['ap'] = ap
    results['map'] = np.asscalar(np.mean(
        [results[l]['ap'] for l in valid_label]))
    return results


def _pred_and_rec_cls(
        bboxes, scores, gt_bboxes, gt_difficults, min_iou=0.5):
    # Calculate detection metrics with respect to a class.
    # This function is called only when there is at least one
    # prediction or ground truth box which is labeled as the class.
    # bboxes: List[numpy.ndarray]
    # scores: List[numpy.ndarray]
    # gt_bboxes: List[numpy.ndarray]
    # gt_difficults: List[numpy.ndarray]

    npos = 0
    selec = [None for _ in six.moves.range(len(gt_bboxes))]
    for i in six.moves.range(len(gt_bboxes)):
        n_gt_bbox = len(gt_bboxes[i])
        selec[i] = np.zeros(n_gt_bbox, dtype=np.bool)
        npos += np.sum(np.logical_not(gt_difficults[i]))

    # Make list of arrays into one array.
    # Example:
    # bboxes = [[bbox00, bbox01], [bbox10]]
    # bbox = array([bbox00, bbox01, bbox10])
    # index = [0, 0, 1]
    index = []
    for i in six.moves.range(len(scores)):
        for j in six.moves.range(len(scores[i])):
            index.append(i)
    index = np.array(index, dtype=np.int)
    conf = np.concatenate(scores)
    bbox = np.concatenate(bboxes)

    if npos == 0 or len(conf) == 0:
        return np.zeros((len(conf),)), np.zeros((len(conf),))

    # Reorder arrays by scores in descending order.
    si = np.argsort(-conf)
    index = index[si]
    bbox = bbox[si]

    nd = len(index)
    tp = np.zeros(nd)
    fp = np.zeros(nd)

    bbox_area = np.prod(bbox[:, 2:] - bbox[:, :2] + 1., axis=1)
    for d in six.moves.range(nd):
        idx = index[d]
        bb = bbox[d]
        ioumax = -np.inf
        gt_bb = gt_bboxes[idx]
        # VOC evaluation follows integer typed bounding boxes.
        gt_bb_area = np.prod(gt_bb[:, 2:] - gt_bb[:, :2] + 1., axis=1)

        if gt_bb.size > 0:
            lt = np.maximum(gt_bb[:, :2], bb[:2])
            rb = np.minimum(gt_bb[:, 2:], bb[2:])
            area = np.prod(np.maximum(rb - lt + 1, 0), axis=1)
            iou = area / (bbox_area[d] + gt_bb_area - area)
            ioumax = np.max(iou)
            jmax = np.argmax(iou)

        if ioumax > min_iou:
            if not gt_difficults[idx][jmax]:
                if not selec[idx][jmax]:
                    tp[d] = 1
                    # assign detections to ground truth objects
                    selec[idx][jmax] = 1
                else:
                    fp[d] = 1
        else:
            fp[d] = 1

    # compute precision/recall
    fp = np.cumsum(fp)
    tp = np.cumsum(tp)
    rec = tp / float(npos)
    prec = tp / np.maximum(fp + tp, np.finfo(np.float64).eps)
    return rec, prec


def _voc_ap(rec, prec, use_07_metric=False):
    if use_07_metric:
        # 11 point metric
        ap = 0.
        for t in np.arange(0., 1.1, 0.1):
            if np.sum(rec >= t) == 0:
                p = 0
            else:
                p = np.max(prec[rec >= t])
            ap = ap + p / 11.
    else:
        # correct AP calculation
        # first append sentinel values at the end
        mrec = np.concatenate(([0.], rec, [1.]))
        mpre = np.concatenate(([0.], prec, [0.]))

        # compute the precision envelope
        for i in six.moves.range(mpre.size - 1, 0, -1):
            mpre[i - 1] = np.maximum(mpre[i - 1], mpre[i])

        # to calculate area under PR curve, look for points
        # where X axis (recall) changes value
        i = np.where(mrec[1:] != mrec[:-1])[0]

        # and sum (\Delta recall) * prec
        ap = np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])
    return ap
