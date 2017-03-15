import os
import base64
import logging
import re
import tempfile
import time

from sys import argv

from apiclient import discovery
from apiclient.http import MediaFileUpload

from AutoUploaderGoogleDrive.auth import Authorize
from AutoUploaderGoogleDrive.rules import Sort
from AutoUploaderGoogleDrive.temp import (setup_temp_file, addentry,
                                          finish_html)
from AutoUploaderGoogleDrive.settingsValidator import settingsLoader

import rarfile

from email.mime.text import MIMEText


__author__ = 'siorai@gmail.com (Paul Waldorf)'


class main(object):
    try:
        script, localFolder = argv
    except:
        print("arg not found")

    def __init__(self, localFolder=None):
        """
        ........ does a lot......

        ........ to be added soon.....
        """
        self.settings = settingsLoader()
        if localFolder:
            self.localFolder = localFolder
        try:
            logFileName = (tempfile.NamedTemporaryFile
                           (dir=self.settings['logPath'],
                            prefix=os.getenv('TR_TORRENT_NAME'),
                            delete=False))
        except(TypeError):
            logFileName = (tempfile.NamedTemporaryFile
                           (dir=self.settings['logPath'],
                            prefix=self.localFolder.rsplit(os.sep)[-2],
                            delete=False))
        logging.basicConfig(stream=logFileName, level=logging.DEBUG)
        http = Authorize()
        self.serviceGmail = discovery.build('gmail', 'v1', http=http)
        self.serviceDrive = discovery.build('drive', 'v2', http=http)
        self.JSONResponseList = []
        self.extractedFilesList = []
        try:
            logging.debug("INIT: ENV: Attempting to load ENV variables")
            self.bt_name = os.getenv('TR_TORRENT_NAME')
            self.bt_dir = os.getenv('TR_TORRENT_DIR')
            if self.bt_name or self.bt_dir is 'None':
                logging.debug("INIT: ENV: Failed find required env.")
                logging.debug("INIT: ENV: Attempting localFolder check")
            else:
                logging.debug("INIT: ENV: Recieved %s as Torrent Name." %
                              self.bt_name)
                logging.debug("INIT: ENV: Recieved %s as Torrent Directory." %
                              self.bt_dir)

            logging.debug("INIT: Extrapolating file path from %s, %s" %
                          (self.bt_name, self.bt_dir))

            self.fullFilePaths = os.path.join(self.bt_dir, self.bt_name)
            logging.debug("INIT: Filepath Directory is %s" %
                          self.fullFilePaths)
            self.autoExtract(self.fullFilePaths)
            if self.settings['enableSorting'] is True:
                updategoogledrivedir = Sort(directory=self.bt_name,
                                            fullPath=self.fullFilePaths)
                logging.debug("***STARTSORT*** %s" % updategoogledrivedir)
            else:
                updategoogledrivedir = ["0", self.settings.googledrivedir]
                logging.debug("***SORTSKIPPED*** %s" % updategoogledrivedir)
            self.destgoogledrivedir = updategoogledrivedir[1]
            self.FilesDict = self.createDirectoryStructure(self.fullFilePaths)
            logging.debug("Creating dictionary of files: %s" % self.FilesDict)
            logging.debug('Information pulled successfully')
        except(AttributeError):
            logging.debug("MAIN: Single file check")

            try:
                if os.path.isfile(self.localFolder) is True:
                    logging.debug("MAIN: Single file: Found for %s" %
                                  self.localFolder)
                    self.singleFileUpload(self.localFolder)
            except(AttributeError):
                print("localFolder not found")
            self.fullFilePaths = self.localFolder
            self.folderName = self.fullFilePaths.rsplit(os.sep)
            logging.debug("Using %s" % self.folderName)
            self.bt_name = self.folderName[-2]
            logging.debug("Using %s" % self.bt_name)
            self.autoExtract(self.fullFilePaths)
            if self.settings['enableSorting'] is True:
                updategoogledrivedir = Sort(directory=self.bt_name,
                                            fullPath=self.fullFilePaths)
                logging.debug("***STARTSORT*** %s" % updategoogledrivedir)
            else:
                updategoogledrivedir = ["0", self.settings['googledrivedir']]
                logging.debug("***SORTSKIPPED*** %s" % updategoogledrivedir)
            self.destgoogledrivedir = updategoogledrivedir[1]
            self.FilesDict = self.createDirectoryStructure(self.fullFilePaths)

        logging.debug("Using %s as FilesDict" % self.FilesDict)
        self.uploadPreserve(self.FilesDict, Folder_ID=self.destgoogledrivedir)
        tempfilename = ('/var/tmp/transmissiontemp/transmission.%s.%s.html' %
                        (self.bt_name, os.getpid()))
        setup_temp_file(tempfilename)
        for EachEntry in self.JSONResponseList:
            addentry(tempfilename, EachEntry)
        finish_html(tempfilename, self.destgoogledrivedir)
        email_subject = ("%s has finished downloading.") % self.bt_name
        email_message = self.encodeMessage(email_subject, tempfilename)
        self.sendMessage(email_message)
        logging.debug("Contents of extractFilesList %s" %
                      self.extractedFilesList)
        self.cleanUp()


    def singleFileUpload(self, localFile):
        logging.debug("MAIN: SINGLE: Found: %s" % localFile)
        FilePath = os.path.abspath(localFile)
        FileTitle = os.path.basename(localFile)
        if self.settings['enableDrivePasteBin'] is True:
            logging.debug("MAIN: SINGLE: Special folder flag returned True.")
            logging.debug("MAIN: SINGLE: Setting remote directory to " +
                          "pastebin")
            remoteDir = self.settings['pastingBinDir']
            email_subject = ("Single file: %s has been uploaded to your pastebin" % FileTitle)
        else:
            logging.debug("MAIN: SINGLE: Special folder flag returned False.")
            logging.debug("MAIN: SINGLE: Setting remote directory to default.")
            remoteDir = self.settings['googleDriveDir']
            email_subject = ("Single file: %s has been uploaded to your " +
                             "default directory")
        logging.debug("MAIN: SINGLE: Uploading to %s" % remoteDir)
        response = self.uploadToGoogleDrive(FilePath,
                                            FileTitle,
                                            Folder_ID=remoteDir)
        self.JSONResponseList.append(response)
        tempfilename = self.tempfilename
        setup_temp_file(tempfilename)
        for EachResponse in self.JSONResponseList:
            addentry(tempfilename, EachResponse)
        finish_html(tempfilename, remoteDir)
        email_message = self.encodeMessage(email_subject, tempfilename)
        self.sendMessage(email_message)
        print("Shortened URL: %s" % response['alt_tiny'])
        quit()

    def createDirectoryStructure(self, rootdir):
        """
        Creates dictionary using os.walk to be used for keeping track
        of the local torrent's file structure to recreate it on Google Drive
        Any folders it finds, it creates a new subdictionary inside, however
        when it locates files adds a list to each entry the first of which is
        'File' and the second of which is the full path/to/file to be used by
        self.uploadToGoogleDrive.

        Args:
            rootdir: string. path/to/directory to be recreated.

        Returns:
            dir: dictionary. Dictionary containing directory file structure and
                full paths to file names
        """
        dir = {}
        rootdir = rootdir.rstrip(os.sep)
        start = rootdir.rfind(os.sep) + 1
        for path, dirs, files in os.walk(rootdir):
            try:
                filepath = os.path.join(path, files)
                folders = path[start:].split(os.sep)
                subdir = dict.fromkeys(files, ['None', filepath])
                parent = reduce(dict.get, folders[:-1], dir)
                parent[folders[-1]] = subdir
            except:
                filepath = path
                folders = path[start:].split(os.sep)
                subdir = dict.fromkeys(files, ['None', filepath])
                parent = reduce(dict.get, folders[:-1], dir)
                parent[folders[-1]] = subdir
        return dir

    def autoExtract(self, directory):
        """
        Function for searching through the specified directory for rar
        archives by performing a simple check for each file in the dir.
        If one is found, it attempts to extract.

        Files that are extracted get appended to self.extractedFilesList
        as a way to keep track of them.

        Once all files in the directory are either uploaded (or skipped if
        they are archives), the extracted files are deleted by the cleanUP
        function.

        Args:
            directory: string. Directory to check for archives
        """
        for path, dirs, files in os.walk(directory):
            for EachFile in files:
                filepath = os.path.join(path, EachFile)
                if rarfile.is_rarfile(filepath):
                    logging.debug("UNRAR: Archive %s found." % filepath)
                    try:
                        logging.debug("UNRAR: Attemping extraction....")
                        with rarfile.RarFile(filepath) as rf:
                            startExtraction = time.time()
                            rf.extractall(path=path)
                            timeToExtract = time.time() - startExtraction
                            for EachExtractedFile in rf.namelist():
                                self.extractedFilesList.append(
                                     {
                                        'FileList': EachExtractedFile,
                                        'Path': path,
                                        'TimeToUnrar': timeToExtract
                                     }
                                                    )
                            logging.debug("UNRAR: Extraction for %s took %s." %
                                          (filepath, timeToExtract))
                    except:
                        logging.debug("UNRAR: Moving onto next file.")

    def cleanUp(self):
        """
        CleanUp script that removes each of the files that was previously
        extracted from archives and deletes from the local hard drive.

        Args:
            None
        """
        logging.debug("CLEANUP: Cleanup started. Deleting extracted files.")
        DeleteFiles = self.extractedFilesList
        for EachFile in DeleteFiles:
            FilePath = os.path.join(EachFile['Path'], EachFile['FileList'])
            logging.debug("CLEANUP: Deleting %s." % FilePath)
            os.remove(FilePath)
        if self.settings['deleteTempHTML'] is True:
            logging.debug("CLEANUP: Deleting HTML File: %s" %
                          self.settings.tempfilename)
            os.remove(self.settings.tempfilename)
        logging.debug("CLEANUP: Cleanup completed.")

    def fetchTorrentFile(self):
        """
        Fetches the Torrents file name to parse for sorting.

        Args:
            bt_name: string. Name of the torrent

        Returns:
            filepath: /path/to/file to be parsed for trackerinfo
        """
        bt_name = self.bt_name
        torrentFileDirectory = self.torrentFileDirectory
        for path, dirs, files in os.walk(torrentFileDirectory):
            for EachTorrent in files:
                if bt_name in EachTorrent:
                    filepath = os.path.join(path, EachTorrent)
                    return filepath

    def getIDs(self):
        """
        Fetches IDs from the Google API to be assigned as needed.

        Args:
            None
        """
        service = self.serviceDrive
        IDs = service.files().generateIds().execute()
        return IDs['ids']

    def createFolder(self, folderName, parents=None):
        """
        Creates folder on Google Drive.

        Args:
            folderName: string.  Name of folder to be created
            parents: Unique ID where folder is to be put inside of

        Returns:
            id: unique folder ID
        """

        service = self.serviceDrive
        body = {'title': folderName,
                'mimeType': 'application/vnd.google-apps.folder'}
        if parents:
            body['parents'] = [{'id': parents}]
        response = service.files().insert(body=body).execute()
        if self.settings['enableNonDefaultPermissions'] is True:
            fileID = response['id']
            self.setPermissions(fileID)
        return response['id']

    def encodeMessage(self, subject, tempfilename, message_text=None):
        """
        Basic MIMEText encoding

        Args:
            subject: string. Subject of email
            tempfilename: string. HTML Table create from temp.py
            message_text: string. optional email text in addition to
                supplied HTML table
        Returns:
            A base64url encoded email object.
        """
        readhtml = open(tempfilename, 'r')
        html = readhtml.read()
        message = MIMEText(html, 'html')
        message['to'] = self.settings['emailTo']
        message['from'] = self.settings['emailSender']
        message['subject'] = subject
        return {'raw': base64.urlsafe_b64encode(message.as_string())}

    def sendMessage(self, message):
        """
        Sends message encoded by encodeMessage.

        Args:
            message: base64url encoded email object.

        Returns:
            JSON response from google.
        """
        service = self.serviceGmail
        response = service.users().messages().send(userId='me',
                                                   body=message).execute()
        return response

    def uploadPreserve(self, FilesDict, Folder_ID=None):
        """
        Uploads files in FilesDict preserving the local file structure
        as shown by FilesDict created from getDirectoryStructure.
        Appends each JSON response from google return as JSON Data into
        self.JSONResponse list.

        Args:
            FilesDict: dict. Dictionary representation of files and structure
                to be created on google drive
            Folder_ID: string. Unique resource ID for folder to be uploaded to.

        Returns:
            Nothing
        """
        for FF in FilesDict:
            i = FilesDict[FF]
            try:
                if i[0]:
                    fullPathToFile = os.path.join(i[1], FF)
                    refilter = re.compile('.*\\.r.*.*\\Z(?ms)')
                    if refilter.match(fullPathToFile):
                        logging.debug("%s skipped." % fullPathToFile)
                    else:
                        response = (self.uploadToGoogleDrive(
                                    fullPathToFile, FF, Folder_ID=Folder_ID))
                        self.JSONResponseList.append(response)
            except(KeyError):
                subfolder = FilesDict[FF]
                subfolder_id = self.createFolder(FF, parents=Folder_ID)
                self.uploadPreserve(subfolder, Folder_ID=subfolder_id)

    def uploadToGoogleDrive(self, FilePath, FileTitle, Folder_ID=None):
        """
        Performs upload to Google Drive.

        Args:
            FilePath: string. Path/To/File/
            FileTitle: string. Passed to the body as the name of the file.
            Folder_ID: string. Unique Folder_ID as assigned by Google Drive.

        Returns:
            Response in the form of JSON data from Google's REST.

        """
        service = self.serviceDrive
        body = {
                'title': FileTitle
        }
        if Folder_ID:
            body['parents'] = [{'id': Folder_ID}]
        startUpload = time.time()
        media = MediaFileUpload(FilePath,
                                chunksize=self.settings['chunkSize'],
                                resumable=True)
        response = service.files().insert(body=body, media_body=media)
        # fileSize = os.path.getsize(FilePath)
        reply = None
        chunkNumber = 0
        while reply is None:
            # chunkStart = time.time()
            status, reply = response.next_chunk()
            if status:
                chunkNumber += 1
                logging.debug("UPLOAD: %s is %f%% complete." %
                              (FileTitle, status.progress()*100))
                # chunkEnd = time.time()
                # logging.debug("UPLOAD: Chunk %i of %i." %
                #               (chunkNumber, chunkEnd - chunkStart))
        print reply
        if self.settings['enableNonDefaultPermissions'] is True:
            fileID = reply['id']
            self.setPermissions(fileID)
        finishUpload = time.time()
        uploadTime = finishUpload - startUpload
        reply['timeToUpload'] = uploadTime
        if self.settings['shortenURL'] is True:
            reply['alt_tiny'] = self.shortenUrl(reply['alternateLink'])
        logging.debug("UPLOAD: %s uploaded. Took %d" % (FileTitle, uploadTime))
        return reply

    def setPermissions(self, file_id):
        """
        Sets the permissions for the file as long as
        settings.enableNonDefaultPermissions is set to True. If set to True,
        the permissions listed there will be applied after each file is
        uploaded to Google Drive.

        Args:
            file_id: string. Unique File ID assigned by google after file is
            uploaded
        """
        service = self.serviceDrive
        newPermissions = {
            'value': self.settings['permissionValue'],
            'type': self.settings['permissionType'],
            'role': self.settings['permissionRole'],
            'withLink': self.settings['withLink'],
            }
        return service.permissions().insert(
            fileId=file_id, body=newPermissions).execute()

    def shortenUrl(self, URL):
        """
        URL Shortener function that when combined with the uploading
        script adds a new key:value to the JSON response with a much
        more managable URL.

        Args:
            URL: string. URL parsed from JSON response
        """
        http = Authorize()
        service = discovery.build('urlshortener', 'v1', http=http)
        url = service.url()
        body = {
            'longUrl': URL
                }
        response = url.insert(body=body).execute()
        logging.debug("URLSHRINK: %s" % response)
        short_url = response['id']
        logging.debug("URLSHRINK: %s" % short_url)
        return short_url


if __name__ == '__main__':
    script, localFolder = argv
    AutoUploaderGoogleDrive(localFolder=localFolder)
