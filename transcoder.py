#!/usr/bin/env python
# -*- encoding: UTF-8 -*-
# @author: wilbur.ma@foxmail.com
# @date:   2013.05.29
# @brief:  Use iconv to transcode text files

import os, optparse, re, fnmatch, tempfile, sys, subprocess

DEFAULT_DELIMITER   = ":"
DEFAULT_FILE_TYPES  = DEFAULT_DELIMITER.join(["*.h", 
                                             "*.hpp", 
                                             "*.cpp", 
                                             "*.cxx", 
                                             "*.c", 
                                             "CMakeLists.txt"])
DEFAULT_FROM_CODE   = "GBK"
DEFAULT_TO_CODE     = "UTF-8"
DEFAULT_BACKUP_FILE = "TranscodeBackup.tgz"

def backup_old_files(tgtDirs):
    targets = " ".join(tgtDirs.split(DEFAULT_DELIMITER))
    ret = os.system("tar --exclude='*.o' --exclude='.svn' -czf %s %s" % (DEFAULT_BACKUP_FILE, targets))
    if 0 == ret:
        print("[Backup] old files %s to %s" % (targets, DEFAULT_BACKUP_FILE))
    else:
        print("[Failed] to backup old files: %s" % targets)

def list_supported_encodings():
    print(subprocess.check_output(["iconv", "-l"]))

def check_iconv():
    if 0 == os.system("iconv -l > /dev/null"):
        return True
    print("[ERROR] iconv not found")
    return False

# @return -1:    inFile not exists or not a regular file
#          0:     transcoding finished successfully
#          other: iconv failed 
def convert_encoding(inFile, outFile, fromCode, toCode):
    if not os.path.isfile(inFile):
        print("[ERROR] %s is not regular file" % inFile)
        return -1
    ret = os.system("iconv -f %s -t %s %s > %s" % (fromCode, toCode, inFile, outFile))
    if 0 == ret:
        print("[Finished] converting %s from %s to %s" % (inFile, fromCode, toCode))
    else:
        print("[Failed] to convert %s from %s to %s" % (inFile, fromCode, toCode))
    return ret

def check_file_encoding(filePath, encoding):
    if not os.path.exists(filePath):
        return False
    if 0 == os.system("file %s | grep %s > /dev/null" % (filePath, encoding)):
        return True
    return False

def is_type_match(fileName, regexList):
    for r in regexList:
        if r.match(fileName) is not None:
            return True
    return False

# build regex objects from file types
def build_regex(fileTypes, caseSensitive=False):
    regexList = []
    for p in fileTypes.split(DEFAULT_DELIMITER):
        if not p:
            continue
        if caseSensitive:
            regexList.append(re.compile(fnmatch.translate(p)))
        else:
            regexList.append(re.compile(fnmatch.translate(p), re.IGNORECASE))
    return regexList

def find_files(tgtDir, regexList):
    if not regexList:
        print("[ERROR] regex list is empty")
        return []
    # search files using regex
    matchedFiles = []
    for (dirPath, subdirs, files) in os.walk(tgtDir):
        matchedFiles.extend([os.path.join(dirPath, f) for f in files if is_type_match(f, regexList)])
    
    return matchedFiles
    

if __name__ == "__main__":
    # init option parser
    parser = optparse.OptionParser()
    parser.add_option("-f", "--from-code", dest="fromCode", default=DEFAULT_FROM_CODE, help="encoding of the input")
    parser.add_option("-t", "--to-code", dest="toCode", default=DEFAULT_TO_CODE, help="encoding of the output")
    parser.add_option("-l", "--list", dest="listEncoding", action="store_true", default=False, help="list supported encodings")
    parser.add_option("-d", "--targetDirs", dest="targetDirs", default=".", help="target directories that hold the source files, use %s as delimiter" % DEFAULT_DELIMITER)
    parser.add_option("-p", "--types", dest="fileTypes", default=DEFAULT_FILE_TYPES, help="file types to convert, use %s as delimiter, default is %s" % (DEFAULT_DELIMITER, DEFAULT_FILE_TYPES))
    parser.add_option("-c", "--case-sensitive", dest="caseSensitive", action="store_true", default=False, help="case sensitive of file types")
    parser.add_option("-n", "--no-backup", dest="noBackup", action="store_true", default=False, help="Do not backup old files")
    (options, args) = parser.parse_args()

    # check iconv
    if not check_iconv():
        sys.exit(1)
    # list supoort encodings:
    if options.listEncoding:
        list_supported_encodings()
    else:
        # backup old files if necessary
        if not options.noBackup:
            backup_old_files(options.targetDirs)
        # do transcoding
        # build regex
        regexList = build_regex(options.fileTypes, options.caseSensitive)
        # convert encodings
        for d in options.targetDirs.split(DEFAULT_DELIMITER):
            print("[Process] ===== directory %s =====" % d)
            if not os.path.isdir(d):
                print("[ERROR] %s is not a directory" % d)
                continue
            for f in find_files(d, regexList):
                if check_file_encoding(f, options.toCode):
                    print("[Skip] %s file %s" % (options.toCode, f))
                    continue
                tempFile = tempfile.NamedTemporaryFile()
                if 0 == convert_encoding(f, tempFile.name, options.fromCode, options.toCode):
                    os.remove(f)
                    os.system("cp %s %s" % (tempFile.name, f))
                tempFile.close()
