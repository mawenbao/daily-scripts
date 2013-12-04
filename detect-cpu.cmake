# detect cpu with uname -m command 
EXECUTE_PROCESS(COMMAND "uname" "-m" OUTPUT_VARIABLE CPU_ARC_NAME)

# remove trailing new-line
STRING(REPLACE "\n" "" CPU_ARC ${CPU_ARC_NAME})

# set precompiled libraries according to cpu architecture
# currently, x86_64 and i686 are supported, example LIB_ENCRYPT: encrypt-x86_64
STRING(REPLACE "ARC" ${CPU_ARC} LIB_ENCRYPT "encrypt-ARC")

