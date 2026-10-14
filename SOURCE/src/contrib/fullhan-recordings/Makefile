CC ?= gcc
CFLAGS ?= -Os
LDFLAGS ?=
TARGET := fullhan-recordings
ARM_FLAGS := -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -marm

.PHONY: all install clean
all: $(TARGET)

$(TARGET): fullhan_recordings.c Makefile
	$(CC) $(CFLAGS) $(ARM_FLAGS) -std=c99 -Wall -Wextra -Werror -static $(LDFLAGS) $< -o $@

install: $(TARGET)
	mkdir -p $(DESTDIR)/bin
	cp $(TARGET) $(DESTDIR)/bin/$(TARGET)

clean:
	rm -f $(TARGET)
