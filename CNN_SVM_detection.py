# set up Python environment: numpy for numerical routines, and matplotlib for plotting
import os
os.environ['GLOG_minloglevel'] = '3' 

import caffe
import itertools
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt
import sys, getopt
import cv2
import pickle
from sklearn import svm
import time
import random
import xml.etree.ElementTree as ET
import hashlib
import glob
from sklearn.metrics import confusion_matrix

from divide_et_impera import extractBBoxesImages, splitTrainTest

from caffe.io import array_to_blobproto
from collections import defaultdict
from skimage import io
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import GridSearchCV

from compute_mean import compute_mean 


netLayers = {
    'googlenet':'pool5/7x7_s1',
    'vggnet':'fc8',
    'resnet':'fc1000'

}


def backspace(n):
    sys.stdout.write('\r'+n)
    sys.stdout.flush()



def createSamplesDatastructures(images_dir, annotations_dir, interesting_labels, mode):


    samplesNames = []
    samplesImages = []
    samplesLabels = []


    if mode == 'voc':

        for root, dirs, files in os.walk(images_dir):
            for image_name in files:
                name, extension = image_name.split(".")

                samplesNames.append(name)

                imageCompletePath = images_dir + '/' + image_name
                image = caffe.io.load_image(imageCompletePath)
                samplesImages.append(image)

                annotationCompletePath = annotations_dir + '/' + name + '.xml'
                label = readLabelFromAnnotation(annotationCompletePath, interesting_labels)
                samplesLabels.append(label)

        imagesFolderPath = images_dir
        annotationsFolderPath = annotations_dir


        return [samplesNames, samplesImages, samplesLabels]





def trainSVMsFromCroppedImages(net, networkName, trainList, images_dir_in, annotations_dir_in, images_dir_out, annotations_dir_out,interesting_labels, gridsearch = False):

    extractBBoxesImages(trainList,images_dir_in,annotations_dir_in, images_dir_out, annotations_dir_out, [])# interesting_labels)

    [filesTrainNames, imagesTrain, labelsTrain] = createSamplesDatastructures(images_dir_out, annotations_dir_out, interesting_labels, 'voc')

    trainFeaturesFileName = 'trainFeatures' + networkName + '.b'

    if not os.path.isfile(trainFeaturesFileName):

        imagesScale = 255.0

        transformer = caffe.io.Transformer({'data': net.blobs['data'].data.shape})
        transformer.set_transpose('data', (2,0,1)) #move image channels to outermost dimension 
        transformer.set_raw_scale('data', imagesScale) 

        #Update the sets of images by transforming them according to Transformer
        for  index in range(len(imagesTrain)):
            imagesTrain[index] = transformer.preprocess('data', imagesTrain[index])

        extractionLayerName = netLayers[networkName]
        t1 = time.time()
        featureVectorsTrain = extractFeatures(imagesTrain, net, extractionLayerName)
        print '\nFeatures extraction took ',(time.time() - t1) ,' seconds for ', len(imagesTrain), ' images'

        #Dump features in a file 
        with open(trainFeaturesFileName, 'wb') as trainFeaturesFile:
            pickle.dump((filesTrainNames, featureVectorsTrain), trainFeaturesFile)

    else:

        print 'Opening old features.... '
        #Load features from a previously dumped file
        with open(trainFeaturesFileName, 'rb') as trainFeaturesFile:
            (filesTrainNames, featureVectorsTrain) = pickle.load(trainFeaturesFile)
            featureVectorsTrain = np.array(featureVectorsTrain)

    imagesClassificationTrain = []
    labelsClassificationTrain = []
    featuresVectorClassificationTrain = []
 
    for idx in range(len(labelsTrain)):
        if labelsTrain[idx] is not 'unknown':
            imagesClassificationTrain.append(imagesTrain[idx])
            labelsClassificationTrain.append(labelsTrain[idx])
            featuresVectorClassificationTrain.append(featureVectorsTrain[idx])


    featureVectorsTrainNormalized = []

    for vec in featureVectorsTrain:
        vecNormalized = vec/np.linalg.norm(vec)
        featureVectorsTrainNormalized.append(vecNormalized)

    trainMean = np.mean(featureVectorsTrainNormalized, axis = 0)

    featureVectorsTrainNormalizedCentered = []

    for vec in featureVectorsTrainNormalized:
        vecCentered = vec - trainMean
        featureVectorsTrainNormalizedCentered.append(vecCentered)



    featureVectorsClassificationTrainNormalized = []

    for vec in featuresVectorClassificationTrain:
        vecNormalized = vec/np.linalg.norm(vec)
        featureVectorsClassificationTrainNormalized.append(vecNormalized)

    classificationTrainMean = np.mean(featureVectorsClassificationTrainNormalized, axis = 0)

    featureVectorsClassificationTrainNormalizedCentered = []

    for vec in featureVectorsClassificationTrainNormalized:
        vecCentered = vec - classificationTrainMean
        featureVectorsClassificationTrainNormalizedCentered.append(vecCentered)





    labelsNovelty = []

    for label in labelsTrain:
        if label == 'unknown':
             labelsNovelty.append(-1)
        else:
             labelsNovelty.append(1)




###########################################

    if gridsearch:

		nu =  [x for x in np.logspace(-4, 0, 20)]  
		gamma = [x for x in np.logspace(-4,0,20)]
		C = [x for x in np.logspace(-1, 10, 30)]
		n_estimators = [int(round(x)) for x in np.logspace(1, 5,20)]
		contamination = [x for x in np.linspace(0, 0.5, 10)]
		classifiers = {
		"oneClass": (svm.OneClassSVM(),{"nu": nu,
		"gamma": gamma}),
		"2Class": (svm.SVC(),{"C": C}),
		"Forest": (IsolationForest(),{"n_estimators": n_estimators,
		"contamination": contamination}	)	}

		score = 0

	
		for name_estimator, (estimator, params) in classifiers.iteritems():
		    print name_estimator
		    clf = GridSearchCV(estimator, params, n_jobs = -1, cv = 5, scoring = "accuracy")
		    if name_estimator is "oneClass" or name_estimator is "Forest":
		        trainDataSet = np.asarray(featureVectorsClassificationTrainNormalizedCentered)
		        labels = [1 for x in range(len(featureVectorsClassificationTrainNormalizedCentered))]
		        clf.fit(trainDataSet, labels)
		    else:
		        trainDataSet = featureVectorsTrainNormalizedCentered

		        labels = labelsNovelty

		        clf.fit(trainDataSet, labels)

		    print "Estimator: ", name_estimator, "\n", clf.best_params_, " score: ", clf.best_score_   

		    if clf.best_score_ > score:
		        score = clf.best_score_
		        noveltySVM = clf.best_estimator_


    else:

		noveltySVM = svm.OneClassSVM(nu=0.0075, kernel = "rbf", gamma = 0.1)

		noveltySVM.fit(featureVectorsClassificationTrainNormalizedCentered)
    



    multiclassSVM = svm.SVC(kernel="rbf", C=1e6, probability=True)

    multiclassSVM.fit(featureVectorsClassificationTrainNormalizedCentered, labelsClassificationTrain)




    return [noveltySVM, multiclassSVM]



def test(net, networkName, noveltySVM, multiclassSVM, testList, images_dir_in, annotations_dir_in, images_dir_out, annotations_dir_out,interesting_labels):

    extractBBoxesImages(testList,images_dir_in,annotations_dir_in, images_dir_out, annotations_dir_out, [])

    [filesTestNames, imagesTest, labelsTest] = createSamplesDatastructures(images_dir_out, annotations_dir_out, interesting_labels, 'voc')

    testFeaturesFileName = 'testFeatures' + networkName + '.b'

    if not os.path.isfile(testFeaturesFileName):
        imagesScale = 255.0

        transformer = caffe.io.Transformer({'data': net.blobs['data'].data.shape})
        transformer.set_transpose('data', (2,0,1)) #move image channels to outermost dimension 
        transformer.set_raw_scale('data', imagesScale) 

        #Update the sets of images by transforming them according to Transformer
        for  index in range(len(imagesTest)):
            imagesTest[index] = transformer.preprocess('data', imagesTest[index])

        
        extractionLayerName = netLayers[networkName]
        t1 = time.time()
        featureVectorsTest = extractFeatures(imagesTest, net, extractionLayerName)
        print '\nFeatures extraction took ',(time.time() - t1) ,' seconds for ', len(imagesTest), ' images'

        #Dump features in a file 
        with open(testFeaturesFileName, 'wb') as testFeaturesFile:
            pickle.dump((filesTestNames, featureVectorsTest), testFeaturesFile)

    else:

        print 'Opening old features.... '
        #Load features from a previously dumped file
        with open(testFeaturesFileName, 'rb') as testFeaturesFile:
            (filesTestNames, featureVectorsTest) = pickle.load(testFeaturesFile)
            featureVectorsTest = np.array(featureVectorsTest)

    featureVectorsTestNormalized = []

    for vec in featureVectorsTest:
        vecNormalized = vec/np.linalg.norm(vec)
        featureVectorsTestNormalized.append(vecNormalized)

    testMean = np.mean(featureVectorsTestNormalized, axis = 0)

    featureVectorsTestNormalizedCentered = []

    for vec in featureVectorsTestNormalized:
        vecCentered = vec - testMean
        featureVectorsTestNormalizedCentered.append(vecCentered)



    correctOutlier = 0
    correctInlier = 0
    correctClass = 0
    numPredicted = 0

    isInliers = noveltySVM.predict(featureVectorsTestNormalizedCentered)
    predictions = multiclassSVM.predict(featureVectorsTestNormalizedCentered)
	
	
    for idx, isInlier in enumerate(isInliers):
        print isInlier
        isInlier = int(isInlier)		
        if isInlier == -1 and labelsTest[idx] == 'unknown':
            correctOutlier+=1
        if isInlier == 1 and labelsTest[idx] is not 'unknown':
            correctInlier+=1
        if isInlier == 1:
            numPredicted+=1
            if predictions[idx] == labelsTest[idx]:
                correctClass+=1

    numInterestingSamples = sum(i is not 'unknown' for i in labelsTest)
    numSamples = len(labelsTest)    
    print 'num interesting labels {}\nunknown {}\ntotal {}\ncorrect outliers {}\ncorrect inlier {}'.format(numInterestingSamples, numSamples-numInterestingSamples, numSamples, correctOutlier, correctInlier)
    
    precision = 100.*correctClass/numPredicted
    recall = 100.*correctClass/numInterestingSamples
    accuracy = 100.*(correctClass + correctOutlier)/numSamples
    noveltyPrecision = 100.* (correctOutlier + correctInlier)/numSamples

    print 'Accuracy: ', accuracy, ' Precision: ', precision, ' Recall: ', recall





def readLabelFromAnnotation(annotationFileName, interesting_labels):
    #Parse the given annotation file and read the label

    tree = ET.parse(annotationFileName)
    root = tree.getroot()
    for obj in root.findall('object'):
        label = obj.find("name").text
        if label in interesting_labels:
            return label
        else:
            return 'unknown'


def extractFeatures(imageSet, net, extractionLayerName):

    featuresVector = []
    totalImages = len(imageSet)
    for num, image in enumerate(imageSet):
        #net.blobs['data'].reshape(1,3,227,227)
        net.blobs['data'].data[...] = image
        net.forward()
        features = net.blobs[extractionLayerName].data[0]
        featuresVector.append(features.copy().flatten())
        string_to_print = '{} of {}'.format(num, totalImages)
        backspace(string_to_print)
    return featuresVector


def plot_confusion_matrix(cm, classes,
                          title='Confusion matrix',
                          cmap=plt.cm.Blues):
    """
    This function prints and plots the confusion matrix.
    Normalization can be applied by setting `normalize=True`.
    """
    cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
    plt.imshow(cm, interpolation='nearest', cmap=cmap)
    plt.title(title)
    plt.colorbar()
    tick_marks = np.arange(len(classes))
    plt.xticks(tick_marks, classes, rotation=45)
    plt.yticks(tick_marks, classes)
    np.set_printoptions(precision=2)

    cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
    thresh = cm.max() / 2.
    for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
        plt.text(j, i, np.around(cm[i, j], decimals=2),
                 horizontalalignment="center",
                 color="white" if cm[i, j] > thresh else "black")

    #print(cm)

    plt.tight_layout()
    plt.ylabel('True labels')
    plt.xlabel('Predicted labels')
    plt.savefig("confusion_matrix.png")




def main(argv):

    model_filename = ''
    weight_filename = ''
    images_dir = 'VOC2007/JPEGImages'
    annotations_dir = 'VOC2007/Annotations'
    caffe.set_mode_cpu()
    try:
        opts, args = getopt.getopt(argv, "hm:w:i:a:n:g")
        print opts
    except getopt.GetoptError:
        print 'CNN_SVM_main.py -m <model_file> -w <weight_file> -i <images_dir> -a <annotations_dir> -n <cnn_type>'
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print 'CNN_SVM_main.py -m <model_file> -w <weight_file> -i <images_dir> -a <annotations_dir> -n <cnn_type>'
            sys.exit()
        elif opt == "-m":
            model_filename = arg
        elif opt == "-w":
            weight_filename = arg
        elif opt == "-i":
            images_dir = arg
        elif opt == "-a":
            annotations_dir = arg
        elif opt == "-n":
        	cnn_type = arg
        elif opt == "-g":
			caffe.set_mode_gpu()
			caffe.set_device(0)
            #print "GPU POWER!!!"



    print 'model file is ', model_filename
    print 'weight file is ', weight_filename
    print 'images dir is ', images_dir
    print 'annotations dir is ', annotations_dir
    print 'the cnn is ', cnn_type	


    interesting_labels = ['aeroplane','bird','cat','boat','horse']
    


    if os.path.isfile(model_filename):
        print 'Caffe model found.'
    else:
        print 'Caffe model NOT found...'
        sys.exit(2)


    #CNN creation
    net = caffe.Net(model_filename,      # defines the structure of the model
                   weight_filename,  # contains the trained weights
                  caffe.TEST)     # use test mode (e.g., don't perform dropout)


    train_images = 'train_images'
    train_annotations = 'train_annotations'

    test_images = 'test_images'
    test_annotations = 'test_annotations'

    percentage = 0.7

    gridsearch = False

    [trainList, testList] = splitTrainTest(annotations_dir, interesting_labels, percentage)

    [noveltySVM, multiclassSVM] = trainSVMsFromCroppedImages(net, cnn_type, trainList, images_dir,annotations_dir,  train_images, train_annotations, interesting_labels, gridsearch)
    
    test(net, cnn_type, noveltySVM, multiclassSVM, testList,images_dir,annotations_dir, test_images,  test_annotations, interesting_labels)




if __name__=='__main__':	
    main(sys.argv[1:])
