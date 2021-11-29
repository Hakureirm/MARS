import sys, os
import MARS_pose_extractor as mpe
import MARS_feature_extractor as mfe
import MARS_classification_extractor as mce
import MARS_classification_machinery as mcm
import MARS_output_format as mof
import MARS_create_video as mcv
import numpy as np
import yaml
import time


class dummyGui():
    def __init__(self):
        self.update_progbar_sig = []


def parse_opts(user_input):
    # fill in missing options with default values
    with open('config.yml') as f:
        opts  = yaml.load(f)
    for f in opts.keys():
        opts[f] = user_input[f] if f in user_input.keys() else opts[f]

    # populate list of behaviors to classify if not provided or empty
    if 'classify_behaviors' not in opts.keys() or not opts['classify_behaviors']:
        if not os.path.isdir(opts['classifier_model']):
            raise ValueError('classifier_model ' + opts['classifier_model'] + 'is not a directory')
        classifier_list = mof.get_classifier_list(opts['classifier_model'])
        behavior_list = [os.path.basename(x).replace('classifier_', '') for x in classifier_list]
        opts['classify_behaviors'] = behavior_list

    return opts


def walk_current_folder(root_path, mars_opts):
    trials_to_run = []
    fullpaths = []
    for path, subdirs, filenames in os.walk(root_path):
        for numv, fname in enumerate(filenames):

            # start by looping over all movie files
            isVideo = any(x in fname for x in mof.get_supported_formats())
            if not isVideo:
                continue

            if mars_opts['hasTopCamera'] and not mars_opts['hasFrontCamera']:
                front_fname, top_fname, mouse_name = mof.get_names(fname, pair_files=False)
                fullpath_to_top = os.path.join(path, top_fname)
                fullpath_to_front = ''

            elif mars_opts['hasFrontCamera'] and not mars_opts['hasTopCamera']:
                front_fname, top_fname, mouse_name = mof.get_names(fname, pair_files=False)
                fullpath_to_top = ''
                fullpath_to_front = os.path.join(path, front_fname)

            elif mars_opts['hasFrontCamera'] and mars_opts['hasTopCamera']:
                front_fname, top_fname, mouse_name = mof.get_names(fname, pair_files=True)
                if top_fname != fname: continue  # only make one entry per top-front pair
                fullpath_to_top = os.path.join(path, top_fname)
                fullpath_to_front = os.path.join(path, front_fname)

            else:
                # This is a movie file, but doesnt have "Top" or "Front" in it. Let's skip it.
                continue

            # Save the paths we want to use.
            mouse_trial = dict()
            mouse_trial['top'] = fullpath_to_top
            mouse_trial['front'] = fullpath_to_front
            trials_to_run.append(mouse_trial)
            fullpaths.append(fullpath_to_top)

    return trials_to_run, fullpaths


def send_update(msg, output_mode='terminal', gui=dummyGui()):
    # this sends output either to the gui or the terminal, depending
    # on which version of MARS is being used.
    if output_mode == 'terminal':
        print(msg)
    else:
        gui.update_progress.emit(msg, msg)


def mars_queue_engine(queue, mars_opts, output_mode, gui_handle=dummyGui()):
    # this gets called either by the gui or by run_MARS
    # it loops over the contents of a queue, and runs MARS on each detected video, with run options set by mars_opts

    mars_opts = parse_opts(mars_opts)
    root_count = 0  # A counter for the number of paths we've processed.

    while not (queue.empty()):
        # While there are still things in the queue...
        time.sleep(0.5)  # (This pause exists to let us see things happening.

        # Get the next path.
        root_path = queue.get()

        # This is a counter for the number of files in this path we've processed. After we reach MAX_FILE_LOGS,
        #   we clear everything. Set MAX_FILE_LOGS to -1 to avoid this feature.
        count = 0
        MAX_FILE_LOGS = 4

        # Walk through the subdirectories and get trials to process.
        msg = "Processing root path " + str(root_count) + " : " + root_path + "\n"
        send_update(msg, output_mode, gui_handle)
        trials_to_run, fullpaths = walk_current_folder(root_path, mars_opts)

        # Get the indices to sort the trials by.
        idxs = np.argsort(fullpaths)

        # Sort the trials.
        placeholder = [trials_to_run[idx] for idx in idxs]
        trials_to_run = placeholder

        # Get the number of videos we're going to process, to give people an impression of time.
        total_valid_videos = len(trials_to_run)
        send_update('Found %d valid videos for analysis.\n' % total_valid_videos, output_mode, gui_handle)
        if output_mode=='gui':
            gui_handle.update_big_progbar_sig.emit(0, total_valid_videos)

        videos_processed = 0
        for trial in trials_to_run:
            try:
                fullpath_to_top = trial['top']
                fullpath_to_front = trial['front']

                top_fname = os.path.basename(fullpath_to_top)
                front_fname = os.path.basename(fullpath_to_front)

                cumulative_progress = ' '.join(
                    [" |", str(videos_processed + 1), "out of", str(total_valid_videos), "total videos"])
                send_update('Processing ' + top_fname + cumulative_progress + '\n', output_mode, gui_handle)

                if not (mars_opts['hasFrontCamera'] | mars_opts['hasTopCamera']):
                    raise ValueError("ERROR: You must select at least one camera to use.")

                if mars_opts['doPose']:
                    if mars_opts['hasFrontCamera']:
                        send_update("   Extracting front pose from " + front_fname + " ... ", output_mode, gui_handle)
                        mpe.extract_pose_wrapper(video_fullpath=fullpath_to_front,
                                                 view='front',
                                                 doOverwrite=mars_opts['doOverwrite'],
                                                 progress_bar_signal=gui_handle.update_progbar_sig,
                                                 mars_opts=mars_opts,
                                                 verbose=mars_opts['verbose'],
                                                 max_frames=mars_opts['max_frames'])
                        send_update("saved.\n", output_mode, gui_handle)
                    if mars_opts['hasTopCamera']:
                        send_update("   Extracting top pose from " + top_fname + " ... ", output_mode, gui_handle)
                        mpe.extract_pose_wrapper(video_fullpath=fullpath_to_top,
                                                 view='top',
                                                 doOverwrite=mars_opts['doOverwrite'],
                                                 progress_bar_signal=gui_handle.update_progbar_sig,
                                                 mars_opts=mars_opts,
                                                 verbose=mars_opts['verbose'],
                                                 max_frames=mars_opts['max_frames'])
                        send_update('saved.\n', output_mode, gui_handle)

                if mars_opts['doFeats']:
                    if not mars_opts['hasTopCamera']:
                        raise ValueError('ERROR: You must have a top-view camera to do feature extraction or behavior classification.')
                    send_update('   Extracting features from ' + top_fname + ' ... ', output_mode, gui_handle)

                    mfe.extract_features_wrapper(opts=mars_opts,
                                                 video_fullpath=fullpath_to_top,
                                                 progress_bar_sig=gui_handle.update_progbar_sig,
                                                 output_suffix='',
                                                 front_video_fullpath=fullpath_to_front)
                    send_update('saved.\n', output_mode, gui_handle)
                    if output_mode == 'gui':
                        gui_handle.update_th.emit(2)

                if mars_opts['doActions']:
                    if not mars_opts['hasTopCamera']:
                        raise ValueError('ERROR: You must have a top-view camera to do behavior classification.')
                    send_update('   Predicting actions from ' + top_fname + ' ... ', output_mode, gui_handle)

                    classifier_path = mars_opts['classifier_model']
                    mce.classify_actions_wrapper(opts=mars_opts,
                                                 top_video_fullpath=fullpath_to_top,
                                                 front_video_fullpath='',
                                                 doOverwrite=mars_opts['doOverwrite'],
                                                 view='top',
                                                 classifier_path=classifier_path)
                    send_update('saved.\n', output_mode, gui_handle)
                    if output_mode == 'gui':
                        gui_handle.update_th.emit(3)

                    mcm.dump_bento(video_fullpath=fullpath_to_top, basepath=root_path)

                if mars_opts['doVideo']:
                    classifier_path = mars_opts['classifier_model']

                    send_update('   Creating results video for ' + top_fname + '...', output_mode, gui_handle)
                    mcv.create_video_results_wrapper(top_video_fullpath=fullpath_to_top,
                                                     classifier_path=classifier_path,
                                                     doOverwrite=mars_opts['doOverwrite'],
                                                     progress_bar_signal=gui_handle.update_progbar_sig,
                                                     view='top')
                    send_update('saved.\n', output_mode, gui_handle)

                if output_mode == 'gui': gui_handle.done_th.emit()
                count += 1
                videos_processed += 1
                if output_mode=='gui':
                    gui_handle.update_big_progbar_sig.emit(videos_processed, 0)
                    if count == MAX_FILE_LOGS:
                        time.sleep(0.5)
                        gui_handle.clear_sig.emit()
                        count = 0

            except Exception as e:
                print(e)
                continue
                # End of try-except block
            # End of particular fname
        # End of the particular root_path
        root_count += 1
    # End of the queue while loop
