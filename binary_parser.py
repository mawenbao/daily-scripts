#!/usr/bin/env python
# -*- encoding: UTF-8 -*-
# @author: wilbur.ma@foxmail.com
# @date: 2013-09-17
# @brief: use python to parse binary file
# @depend: construct
#          structs_little_endian.py or structs_big_endian.py

import os, sys, struct, codecs, inspect, binascii, optparse, construct

def write_dict(fdWriter, dictObj):
    fdWriter.write("{")
    keys = dictObj.keys()
    for x in xrange(len(keys)):
        item = '"{}":"{}"'.format(keys[x], dictObj[keys[x]].strip("\0"))
        fdWriter.write(item)
        if x != len(keys) - 1:
            fdWriter.write(",")
    fdWriter.write("}")

ProtobufMap = {
    "proto.News": [1,20],
}

class BinaryFileParser(object):
    def __init__(self, protoDir, littleEndian=True):
        self.encoding = "GBK"
        self.script_path = os.path.dirname(inspect.getfile(inspect.currentframe()))
        self.little_endian = littleEndian
        self.structs_module = "structs_{}".format(
                "little_endian" if self.little_endian else "big_endian")
        if not os.path.isfile(os.path.join(self.script_path, "{}.py".format(self.structs_module))):
            print("ERROR: python.construct dsl file {}.py not found in {}".format(
                self.structs_module, self.script_path))
            sys.exit(1)
        __import__(self.structs_module)
        self.protobuf_map = {} # mq category => proto pkg.class
        self._index_protobuf_map()
        self.proto_dir = protoDir
        sys.path.append(self.proto_dir)
        self.protobuf_cls_map = {} # proto pkg.class => proto class object

    def _index_protobuf_map(self):
        for key, value in ProtobufMap.items():
            for v in value:
                if self.protobuf_map.has_key(v):
                    print("ERROR: duplicate mq category in ProtobufMap: {}".format(v))
                    sys.exit(1)
                self.protobuf_map[v] = key

    def _parse_proto_cls_name(self, protoPkgClsName):
        protoClsName = protoPkgClsName.split(".")[-1]
        return ("{}_pb2".format(protoClsName), protoClsName)

    def dict2protobuf(self, category, dictObj):
        if not category in self.protobuf_map:
            print("ERROR: {} not in registered in ProtobufMap".format(category))
            return None
        protoPkgClsName = self.protobuf_map[category]
        if protoPkgClsName not in self.protobuf_cls_map:
            protoFileName, protoClsName = self._parse_proto_cls_name(protoPkgClsName)
            # the structs_{little|big}_endian.py should reside in the same directory
            __import__(protoFileName)
            self.protobuf_cls_map[protoPkgClsName] = getattr(sys.modules[protoFileName], protoClsName)

        protoCls = self.protobuf_cls_map[protoPkgClsName]
        if not protoCls:
            return None

        proto = protoCls()
        for fieldDesc in proto.DESCRIPTOR.fields:
            field = fieldDesc.name
            if field in dictObj:
                val = dictObj[field] if type(dictObj[field]) != unicode else str(dictObj[field])
                setattr(proto, field, val)
        return proto

    def generate_protobuf_list(self, category, listContainer):
        protoList = []
        for protoDict in listContainer:
            protoList.append(self.dict2protobuf(category, protoDict))
        return protoList

    def parse_binary_data(self, category, binInputData):
        if int != type(category):
            print("ERROR: category should be a number: {}".format(category))
            return None

        retStructName = "STRUCT_RET_{}".format(category)
        if not hasattr(sys.modules[self.structs_module], retStructName):
            print("ERROR: the return struct {} was not declared".format(retStructName))
            return None

        retStruct = getattr(sys.modules[self.structs_module], retStructName)
        return retStruct.parse(binInputData)

    # parse binary data and return:
    # 1) head: json string
    # 2) body: generated protobuf as binary string, only support little-endian for now
    #          crc32 checksum, protobuf-name-size, protobuf-name, count, proto-data-size, proto-data, proto-data-size, proto-data, ...
    def parse_binary_to_protobuf(self, category, binInputData):
        if category not in self.protobuf_map:
            print("ERROR: {} not registered in ProtobufMap".format(category))
            return

        protoFullName = self.protobuf_map[category]
        result = struct.pack("<i", len(protoFullName))
        result += struct.pack("{}s".format(len(protoFullName)), protoFullName)
        container = self.parse_binary_data(category, binInputData)

        jsonHead = {}
        for k, v in container.items():
            if k not in ProtobufMap:
                # parse head
                if not isinstance(v, list):
                    jsonHead[k] = str(v)
            # parse body
            elif isinstance(v, list):
                protoList = self.generate_protobuf_list(category, v)
                # proto count
                result += struct.pack("<i", len(protoList))
                # proto data array
                for proto in protoList:
                    protoBinStr = proto.SerializeToString()
                    result += struct.pack("<i", len(protoBinStr))
                    result += protoBinStr
            else:
                result += struct.pack("<i", 1)
                proto = self.dict2protobuf(category, v)
                protoBinStr = proto.SerializeToString()
                result += len(protoBinStr)
                result += protoBinStr

        #head = json.dumps(jsonHead, ensure_ascii=False)
        #head = str(jsonHead).replace("'", '"')
        # calc crc32 and return
        body = struct.pack("<i", binascii.crc32(result)) + result
        return jsonHead, body

if __name__ == "__main__":
    cmdParser = optparse.OptionParser()
    cmdParser.add_option("-f", "--file", dest="dataFile", help="Path of the poehost response data file")
    cmdParser.add_option("-c", "--category", type="int", dest="category", help="Protocol category(mq id) of the binary data file")
    cmdParser.add_option("-H", "--head", dest="head", help="Output head part to a json file")
    cmdParser.add_option("-B", "--body", dest="body", help="Output body part to a protobuf pack file")
    cmdParser.add_option("-p", "--proto-dir", dest="protoDir", help="Directory which contains the generated python protobuf message class")
    cmdParser.add_option("-b", "--big-endian", dest="littleEndian", action="store_false", default=True, help="Use big endian, default little endian")
    options, args = cmdParser.parse_args()

    if not options.dataFile or not options.protoDir or not options.category:
        print("ERROR: no input data file or no protobuf directory or no category")
        sys.exit(1)
    if not os.path.isfile(options.dataFile):
        print("ERROR: {} is not a regular file".format(options.dataFile))
        sys.exit(1)

    parser = BinaryFileParser(options.protoDir, options.littleEndian)
    with open(options.dataFile, "rb") as f:
        binInputData = f.read()
        jsonHead, binBody = parser.parse_binary_to_protobuf(options.category, binInputData)

        if options.head:
            with open(options.head, "w") as of:
                write_dict(of, jsonHead)
                #codecs.getwriter(parser.encoding)(of).write(jsonHead)
                # remove double quotes in the beginning and end, and remove back slashes
                #of.write(json.dumps(jsonHead).replace('\\', '').strip('"'))
                #pprint.pprint(jsonHead, of)
        else:
            sys.stdout.write(jsonHead)

        if options.body:
            with open(options.body, "wb") as of:
                of.write(binBody)
        else:
            sys.stdout.write(binBody)

