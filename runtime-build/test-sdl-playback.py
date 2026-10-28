#!/usr/bin/env python3
"""Compile actual SDL playback paths with fake endpoints and deterministic clocks."""
import argparse
from pathlib import Path
import shlex
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path, help='patched QEMU source directory')
cases = ('empty-inventory-pacing', 'reconnect-resumes',
         'failed-open-backoff', 'stopped-device-release',
         'route-selection-returns', 'mixeng-ring-drains')
parser.add_argument('--case', choices=cases, help='run one regression case')
args = parser.parse_args()
root = args.source
source = (root / 'audio/sdlaudio.c').read_text(encoding='utf-8')
mixeng = (root / 'audio/audio-mixeng-be.c').read_text(encoding='utf-8')
internal = (root / 'audio/audio_int.h').read_text(encoding='utf-8')


def section(text, start, end):
    return text[text.index(start):text.index(end, text.index(start))]


harness = r'''
#include <assert.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define _WIN32 1
#define NANOSECONDS_PER_SECOND 1000000000
#define trace_audio_rate_reset(...) ((void)0)
static int64_t virtual_ns;
static gint64 host_us;
static gint64 fake_monotonic_time(void) { return host_us; }
#define g_get_monotonic_time fake_monotonic_time
static int64_t qemu_clock_get_ns(int clock) { return virtual_ns; }
static uint64_t muldiv64(uint64_t a, uint64_t b, uint64_t c) {
    return (uint64_t)(((__uint128_t)a * b) / c);
}
static uint16_t bswap16(uint16_t v) { return __builtin_bswap16(v); }
static uint32_t bswap32(uint32_t v) { return __builtin_bswap32(v); }
typedef enum {
    AUDIO_FORMAT_U8, AUDIO_FORMAT_U16, AUDIO_FORMAT_U32,
    AUDIO_FORMAT_S8, AUDIO_FORMAT_S16, AUDIO_FORMAT_S32, AUDIO_FORMAT_F32,
    AUDIO_FORMAT__MAX
} AudioFormat;
struct audio_pcm_info {
    int bytes_per_frame, bytes_per_second, nchannels;
    AudioFormat af;
    bool swap_endianness;
};
typedef struct {
    struct audio_pcm_info info;
    size_t samples;
    size_t size_emul, pos_emul, pending_emul;
    unsigned char *buf_emul;
    void *s;
} HWVoiceOut;
typedef void Audiodev;
typedef unsigned SDL_AudioDeviceID;
typedef unsigned char Uint8;
typedef struct {
    int freq, format, channels, samples;
    void *callback, *userdata;
} SDL_AudioSpec;
#define SDL_AUDIO_STOPPED 0
#define SDL_AUDIO_PLAYING 1
#define SDL_AUDIO_PAUSED 2
typedef struct AudioMixengBackendClass {
    size_t (*buffer_get_free)(HWVoiceOut *hw);
    void *(*get_buffer_out)(HWVoiceOut *hw, size_t *size);
    size_t (*put_buffer_out)(HWVoiceOut *hw, void *buf, size_t size);
    size_t (*write)(HWVoiceOut *hw, void *buf, size_t size);
} AudioMixengBackendClass;
#define AUDIO_MIXENG_BACKEND_GET_CLASS(s) ((AudioMixengBackendClass *)(s))
#define unlikely(x) (x)
#define likely(x) (x)
#define QEMU_CLOCK_VIRTUAL 0
static int playback_count, enumerations, opens, closes, failures, status;
static bool fail_open, incompatible;
static gint64 failed_open_us;
static const char *last_name;
static const char *listed_name = "Speaker";
#define warn_report(...) ((void)0)
#define error_report(...) (failures++)
static void SDL_ClearError(void) {}
static const char *SDL_GetError(void) { return "unavailable"; }
static int SDL_GetNumAudioDevices(int rec) {
    assert(rec == 0);
    enumerations++;
    return playback_count;
}
static const char *SDL_GetAudioDeviceName(int index, int rec) {
    assert(rec == 0);
    (void)index;
    return listed_name;
}
static SDL_AudioDeviceID SDL_OpenAudioDevice(const char *name, int rec,
        SDL_AudioSpec *req, SDL_AudioSpec *obt, int changes) {
    /* A Windows session without playback endpoints must never reach WASAPI:
     * a failed activation blocks for eight seconds inside the audio path. */
    opens++;
    assert(rec == 0 && playback_count > 0 && changes == 0);
    last_name = name;
    if (fail_open || (name && strcmp(name, listed_name))) {
        host_us += failed_open_us;
        return 0;
    }
    *obt = *req;
    if (incompatible) {
        obt->freq++;
    }
    status = SDL_AUDIO_PAUSED;
    return 23;
}
static int SDL_GetAudioDeviceStatus(SDL_AudioDeviceID id) {
    assert(id == 23);
    return status;
}
static void SDL_PauseAudioDevice(SDL_AudioDeviceID id, int paused) {
    assert(id == 23);
    status = paused ? SDL_AUDIO_PAUSED : SDL_AUDIO_PLAYING;
}
static void SDL_CloseAudioDevice(SDL_AudioDeviceID id) {
    assert(id == 23);
    closes++;
    status = SDL_AUDIO_STOPPED;
}
static void SDL_LockAudioDevice(SDL_AudioDeviceID id) { assert(id == 23); }
static void SDL_UnlockAudioDevice(SDL_AudioDeviceID id) { assert(id == 23); }
static size_t audio_ring_posb(size_t pos, size_t pending, size_t size) {
    return (pos + size - pending) % size;
}
#define xglue(a, b) a##b
#define glue(a, b) xglue(a, b)
#define MAKE_IDENTIFIER(x) glue(x, __COUNTER__)
#define MIN_INTERNAL(a, b, _a, _b) \
    ({ typeof(1 ? (a) : (b)) _a = (a), _b = (b); _a < _b ? _a : _b; })
#undef MIN
#define MIN(a, b) MIN_INTERNAL((a), (b), MAKE_IDENTIFIER(_a), MAKE_IDENTIFIER(_b))
''' + section(
    internal, 'typedef struct RateCtl {', 'void audio_rate_start(') + section(
    source, 'typedef struct SDLVoiceOut {', 'typedef struct SDLVoiceIn {') + section(
    mixeng, 'void audio_pcm_info_clear_buf(', '/*') + section(
    mixeng, 'void audio_generic_initialize_buffer_out(', 'size_t audio_generic_write(') + section(
    mixeng, 'size_t audio_generic_write(', 'size_t audio_generic_read(') + section(
    mixeng, 'void audio_rate_start(', 'static const TypeInfo audio_types[]') + section(
    source, 'static char *sdl_initial_device_name(', 'static void sdl_close_out(') + section(
    source, 'static void sdl_callback_out(', 'static void sdl_close_in(') + section(
    source, 'static void sdl_release_out(', '/* The recording counterpart of sdl_release_out(). */') + section(
    source, '#define SDL_WRAPPER_FUNC', 'SDL_WRAPPER_FUNC(read,') + section(
    source, 'static size_t sdl_write(', 'static int sdl_init_out(') + section(
    source, 'static void sdl_enable_out(', 'static void sdl_fini_in(') + r'''
static AudioMixengBackendClass fake_backend_class = {
    audio_generic_buffer_get_free,
    audio_generic_get_buffer_out,
    audio_generic_put_buffer_out,
    audio_generic_write,
};

static void reset_state(void)
{
    virtual_ns = 0;
    host_us = 0;
    playback_count = enumerations = opens = closes = failures = 0;
    fail_open = incompatible = false;
    failed_open_us = 0;
    last_name = NULL;
    listed_name = "Speaker";
    status = SDL_AUDIO_STOPPED;
    g_unsetenv("OMARCHY_SDL_AUDIO_CONTROL_DIRECTORY");
}

static SDLVoiceOut make_voice(void)
{
    SDLVoiceOut sdl = {0};

    sdl.hw.info = (struct audio_pcm_info){4, 192000, 2, AUDIO_FORMAT_S16, false};
    sdl.hw.samples = 1024;
    sdl.hw.s = &fake_backend_class;
    sdl.reopen_spec = (SDL_AudioSpec){48000, 1, 2, 512, NULL, NULL};
    return sdl;
}

static void advance(int milliseconds)
{
    host_us += milliseconds * 1000;
    virtual_ns += milliseconds * 1000000;
}

static size_t write_guest(SDLVoiceOut *sdl, size_t size)
{
    unsigned char buffer[4096] = {0};

    assert(size <= sizeof(buffer));
    memset(buffer, 0x5a, size);
    return sdl_write(&sdl->hw, buffer, size);
}

static size_t drain_device(SDLVoiceOut *sdl, size_t length)
{
    unsigned char buffer[4096];
    size_t before = sdl->hw.pending_emul;

    assert(length <= sizeof(buffer));
    sdl_callback_out(sdl, buffer, (int)length);
    return before - sdl->hw.pending_emul;
}

static int case_empty_inventory_pacing(void)
{
    reset_state();
    playback_count = 0;
    SDLVoiceOut sdl = make_voice();
    sdl_enable_out(&sdl.hw, true);
    assert(sdl.enabled && !sdl.devid && opens == 0 && enumerations == 2);

    gint64 start = host_us;
    for (int i = 0; i < 50; i++) {
        advance(10);
        assert(write_guest(&sdl, 1920) == 1920);
    }
    /* No WASAPI open is attempted and no failed activation delays the loop. */
    assert(opens == 0);
    assert(enumerations == 2);
    assert(host_us - start == 500000);
    sdl_enable_out(&sdl.hw, false);
    puts("ok - empty playback inventory never opens WASAPI and keeps periods moving");
    return 0;
}

static int case_reconnect_resumes(void)
{
    reset_state();
    playback_count = 0;
    SDLVoiceOut sdl = make_voice();
    sdl_enable_out(&sdl.hw, true);
    assert(!sdl.devid && opens == 0);

    advance(1000); /* the one-second retry becomes due */
    playback_count = 1;
    assert(write_guest(&sdl, 1920) == 1920);
    assert(opens == 1 && sdl.devid == 23 && status == SDL_AUDIO_PLAYING);
    assert(sdl.hw.pending_emul == 1920);
    assert(drain_device(&sdl, 1920) == 1920);
    assert(sdl.hw.pending_emul == 0);
    sdl_enable_out(&sdl.hw, false);
    puts("ok - playback resumes from the first period after an endpoint returns");
    return 0;
}

static int case_mixeng_ring_drains(void)
{
    reset_state();
    playback_count = 0;
    SDLVoiceOut sdl = make_voice();
    sdl_enable_out(&sdl.hw, true);
    assert(!sdl.devid && opens == 0);

    /* The default mixing engine stages mixed samples in the backend ring. */
    size_t size = 0;
    void *buf = audio_generic_get_buffer_out(&sdl.hw, &size);
    assert(size == 4096);
    memset(buf, 0, size);
    assert(audio_generic_put_buffer_out(&sdl.hw, buf, size) == size);
    assert(sdl.hw.pending_emul == 4096);
    assert(sdl_buffer_get_free(&sdl.hw) == 0);
    /* The ring must not stay full while there is no playback device. */
    advance(10);
    assert(sdl_buffer_get_free(&sdl.hw) == 1920);
    assert(sdl.hw.pending_emul == 4096 - 1920);
    advance(10);
    assert(sdl_buffer_get_free(&sdl.hw) == 3840);
    assert(sdl.hw.pending_emul == 256);
    assert(opens == 0);
    sdl_enable_out(&sdl.hw, false);
    puts("ok - a missing playback device drains the mixing-engine ring at the virtual clock");
    return 0;
}

static int case_failed_open_backoff(void)
{
    reset_state();
    playback_count = 1;
    fail_open = true;
    failed_open_us = 8 * G_USEC_PER_SEC;
    SDLVoiceOut sdl = make_voice();
    sdl_enable_out(&sdl.hw, true);
    assert(opens == 1 && failures == 1 && !sdl.devid);
    assert(sdl.next_route_check == host_us + 10 * G_USEC_PER_SEC);

    for (int i = 0; i < 999; i++) {
        advance(10);
        assert(write_guest(&sdl, 1920) == 1920);
    }
    assert(opens == 1);
    advance(10);
    assert(write_guest(&sdl, 1920) == 1920);
    assert(opens == 2 && failures == 2 && !sdl.devid);

    fail_open = false;
    failed_open_us = 0;
    advance(10000);
    assert(write_guest(&sdl, 1920) == 1920);
    assert(opens == 3 && sdl.devid == 23 && status == SDL_AUDIO_PLAYING);
    assert(drain_device(&sdl, 1920) == 1920);
    sdl_enable_out(&sdl.hw, false);
    puts("ok - failed playback opens wait ten seconds and stream pacing continues");
    return 0;
}

static int case_stopped_device_release(void)
{
    reset_state();
    playback_count = 1;
    SDLVoiceOut sdl = make_voice();
    sdl_enable_out(&sdl.hw, true);
    assert(opens == 1 && sdl.devid == 23 && status == SDL_AUDIO_PLAYING);
    assert(write_guest(&sdl, 1920) == 1920);
    assert(sdl.hw.pending_emul == 1920);

    /* The endpoint vanished: SDL reports the device stopped. */
    playback_count = 0;
    status = SDL_AUDIO_STOPPED;
    assert(write_guest(&sdl, 1920) == 0);
    assert(closes == 1 && !sdl.devid && opens == 1);
    assert(sdl.hw.pending_emul == 0);
    for (int i = 0; i < 100; i++) {
        advance(10);
        assert(write_guest(&sdl, 1920) == 1920);
    }
    /* Only enumerations grew; WASAPI was never asked to open a missing device. */
    assert(opens == 1);

    playback_count = 1;
    advance(1000);
    assert(write_guest(&sdl, 1920) == 1920);
    assert(opens == 2 && sdl.devid == 23 && status == SDL_AUDIO_PLAYING);
    assert(drain_device(&sdl, 1920) == 1920);
    sdl_enable_out(&sdl.hw, false);
    puts("ok - a stopped playback device is released, paced as silence and reacquired");
    return 0;
}

static int case_route_selection_returns(void)
{
    reset_state();
    playback_count = 1;
    SDLVoiceOut sdl = make_voice();
    g_autofree char *directory = g_dir_make_tmp("tryomarchy-playback-XXXXXX", NULL);
    assert(directory);
    g_autofree char *output = g_build_filename(directory, "output", NULL);
    g_setenv("OMARCHY_SDL_AUDIO_CONTROL_DIRECTORY", directory, TRUE);
    /* "Missing" base64-encoded, matching the launcher's route file format. */
    assert(g_file_set_contents(output, "TWlzc2luZw==\n", -1, NULL));

    sdl_enable_out(&sdl.hw, true);
    assert(opens == 1 && sdl.devid == 23 && !sdl.route_matches);
    assert(last_name == NULL); /* the system default was opened instead */
    assert(write_guest(&sdl, 1920) == 1920);

    listed_name = "Missing";
    advance(250);
    assert(write_guest(&sdl, 1920) == 1920);
    assert(opens == 2 && sdl.route_matches);
    assert(last_name && !strcmp(last_name, "Missing"));
    assert(drain_device(&sdl, 4096) == 3840);
    sdl_enable_out(&sdl.hw, false);
    assert(g_remove(output) == 0);
    assert(g_rmdir(directory) == 0);
    g_unsetenv("OMARCHY_SDL_AUDIO_CONTROL_DIRECTORY");
    puts("ok - a missing selection falls back to the default and returns when listed");
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 1) {
        case_empty_inventory_pacing();
        case_reconnect_resumes();
        case_mixeng_ring_drains();
        case_failed_open_backoff();
        case_stopped_device_release();
        case_route_selection_returns();
        puts("ok - no-endpoint playback, reconnect, backoff, stopped-device and route recovery");
        return 0;
    }
    if (!strcmp(argv[1], "empty-inventory-pacing")) {
        return case_empty_inventory_pacing();
    }
    if (!strcmp(argv[1], "reconnect-resumes")) {
        return case_reconnect_resumes();
    }
    if (!strcmp(argv[1], "mixeng-ring-drains")) {
        return case_mixeng_ring_drains();
    }
    if (!strcmp(argv[1], "failed-open-backoff")) {
        return case_failed_open_backoff();
    }
    if (!strcmp(argv[1], "stopped-device-release")) {
        return case_stopped_device_release();
    }
    if (!strcmp(argv[1], "route-selection-returns")) {
        return case_route_selection_returns();
    }
    return 2;
}
'''
with tempfile.TemporaryDirectory(prefix='tryomarchy-sdl-playback-') as temporary:
    test = Path(temporary)
    (test / 'test.c').write_text(harness, encoding='utf-8')
    flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True))
    subprocess.run(['gcc', '-std=gnu11', '-O2', '-Wall', '-Wextra',
                    '-Wno-unused-parameter', '-Wno-unused-function',
                    '-Werror', str(test / 'test.c'), '-o', str(test / 'test'),
                    *flags], check=True)
    selected = (args.case,) if args.case else (None, *cases)
    for case in selected:
        command = [str(test / 'test')]
        if case:
            command.append(case)
        subprocess.run(command, check=True)
