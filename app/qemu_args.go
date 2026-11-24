package main

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const (
	extraQEMUArgsFileName = "qemu-args.txt"
	maxExtraQEMUArgsBytes = 64 << 10
)

// extraQEMUArgsPath keeps the advanced arguments out of settings.json: older
// launchers reject unknown settings fields, but they ignore unknown files.
func extraQEMUArgsPath(dir string) string {
	return filepath.Join(dir, extraQEMUArgsFileName)
}

func loadExtraQEMUArgs(dir string) (string, error) {
	data, err := os.ReadFile(extraQEMUArgsPath(dir))
	if errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	if len(data) > maxExtraQEMUArgsBytes {
		return "", fmt.Errorf("%s is too large", extraQEMUArgsFileName)
	}
	// Notepad can save UTF-8 with a byte-order mark.
	return string(bytes.TrimPrefix(data, []byte("\xef\xbb\xbf"))), nil
}

// saveExtraQEMUArgs writes the field atomically. An empty value removes the
// file, so an installation without arguments leaves nothing behind.
func saveExtraQEMUArgs(dir, value string) error {
	value = strings.TrimSpace(value)
	path := extraQEMUArgsPath(dir)
	if value == "" {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		return nil
	}
	tmp := path + ".part"
	if err := os.WriteFile(tmp, []byte(value+"\n"), 0o644); err != nil {
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return err
	}
	return nil
}

// splitQEMUArgs turns the advanced settings field into QEMU arguments. Spaces
// separate arguments and double quotes group a value that contains spaces.
// Nothing is validated: an unbalanced quote keeps the rest as one argument,
// and QEMU then reports the real error at startup like any other bad option.
func splitQEMUArgs(value string) []string {
	var args []string
	var arg strings.Builder
	started, quoted := false, false
	for i := 0; i < len(value); i++ {
		switch c := value[i]; {
		case quoted:
			if c == '"' {
				quoted = false
				continue
			}
			arg.WriteByte(c)
		case c == '"':
			quoted, started = true, true
		case c == ' ' || c == '\t' || c == '\r' || c == '\n':
			if started {
				args = append(args, arg.String())
				arg.Reset()
				started = false
			}
		default:
			arg.WriteByte(c)
			started = true
		}
	}
	if started {
		args = append(args, arg.String())
	}
	return args
}
