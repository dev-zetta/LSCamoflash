CC ?= gcc
CFLAGS ?= -Os
LDFLAGS ?=
TARGET := libcamoflash_rtsp.so
ARM_FLAGS := -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -marm

.PHONY: all install clean
all: $(TARGET)

$(TARGET): rtsp_callback.c Makefile
	$(CC) $(CFLAGS) $(ARM_FLAGS) -std=c99 -Wall -Wextra -Werror -fPIC -shared -Wl,-z,defs $(LDFLAGS) $< -ldl -pthread -o $@

install: $(TARGET)
	mkdir -p $(DESTDIR)/lib
	cp $(TARGET) $(DESTDIR)/lib/$(TARGET)

clean:
	rm -f $(TARGET)
