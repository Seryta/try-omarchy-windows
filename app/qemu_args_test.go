package main

import (
	"os"
	"reflect"
	"strings"
	"testing"
)

func TestSplitQEMUArgs(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want []string
	}{
		{"empty", "", nil},
		{"whitespace", " \t\r\n ", nil},
		{"plain", "-drive file=/data.raw,format=raw,if=virtio",
			[]string{"-drive", "file=/data.raw,format=raw,if=virtio"}},
		{"quoted value with spaces", `-drive "file=D:\My Data\data.raw,format=raw,if=virtio"`,
			[]string{"-drive", `file=D:\My Data\data.raw,format=raw,if=virtio`}},
		{"quoted token", `-name "Try Omarchy" -smp 4`,
			[]string{"-name", "Try Omarchy", "-smp", "4"}},
		{"unbalanced quote keeps the rest", `-drive "file=D:\data.raw -smp 4`,
			[]string{"-drive", `file=D:\data.raw -smp 4`}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := splitQEMUArgs(tc.in); !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("splitQEMUArgs(%q) = %#v, want %#v", tc.in, got, tc.want)
			}
		})
	}
}

func TestExtraQEMUArgsRoundTrip(t *testing.T) {
	dir := t.TempDir()
	if got, err := loadExtraQEMUArgs(dir); err != nil || got != "" {
		t.Fatalf("missing file = %q, %v; want empty", got, err)
	}
	value := `-drive "file=D:\My Data\data.raw,format=raw,if=virtio"`
	if err := saveExtraQEMUArgs(dir, "  "+value+"  "); err != nil {
		t.Fatal(err)
	}
	got, err := loadExtraQEMUArgs(dir)
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(got) != value {
		t.Fatalf("loaded %q, want %q", got, value)
	}
	if args := splitQEMUArgs(got); !reflect.DeepEqual(args, []string{"-drive", `file=D:\My Data\data.raw,format=raw,if=virtio`}) {
		t.Fatalf("split saved arguments = %#v", args)
	}
	if err := saveExtraQEMUArgs(dir, "   "); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(extraQEMUArgsPath(dir)); !os.IsNotExist(err) {
		t.Fatalf("empty value left %s behind", extraQEMUArgsFileName)
	}
}

func TestBuildQemuArgsAppendsExtraQEMUArgsLast(t *testing.T) {
	cfg := &config{vmDir: "/vm", guestDir: "/guest", disk: "/vm/disk.raw",
		diskFormat: "raw", memMiB: 4096, audio: "none"}
	cfg.extraQEMUArgs = []string{"-drive", "file=/data.raw,format=raw,if=virtio"}
	args := buildQemuArgs(cfg, "root=/dev/vda")
	if len(args) < 2 {
		t.Fatalf("QEMU arguments are too short: %#v", args)
	}
	if got := args[len(args)-2:]; !reflect.DeepEqual(got, cfg.extraQEMUArgs) {
		t.Fatalf("advanced arguments are not last: %#v", got)
	}
}
