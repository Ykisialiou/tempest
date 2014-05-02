#!/usr/bin/env python

# Copyright 2014 Hewlett-Packard Development Company, L.P.
# Copyright 2014 Samsung Electronics
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Trace a subunit stream in reasonable detail and high accuracy."""

import functools
import sys

import mimeparse
import subunit
import testtools

DAY_SECONDS = 60 * 60 * 24
FAILS = []
RESULTS = {}


class Starts(testtools.StreamResult):

    def __init__(self, output):
        super(Starts, self).__init__()
        self._output = output

    def startTestRun(self):
        self._neednewline = False
        self._emitted = set()

    def status(self, test_id=None, test_status=None, test_tags=None,
               runnable=True, file_name=None, file_bytes=None, eof=False,
               mime_type=None, route_code=None, timestamp=None):
        super(Starts, self).status(
            test_id, test_status,
            test_tags=test_tags, runnable=runnable, file_name=file_name,
            file_bytes=file_bytes, eof=eof, mime_type=mime_type,
            route_code=route_code, timestamp=timestamp)
        if not test_id:
            if not file_bytes:
                return
            if not mime_type or mime_type == 'test/plain;charset=utf8':
                mime_type = 'text/plain; charset=utf-8'
            primary, sub, parameters = mimeparse.parse_mime_type(mime_type)
            content_type = testtools.content_type.ContentType(
                primary, sub, parameters)
            content = testtools.content.Content(
                content_type, lambda: [file_bytes])
            text = content.as_text()
            if text and text[-1] not in '\r\n':
                self._neednewline = True
            self._output.write(text)
        elif test_status == 'inprogress' and test_id not in self._emitted:
            if self._neednewline:
                self._neednewline = False
                self._output.write('\n')
            worker = ''
            for tag in test_tags or ():
                if tag.startswith('worker-'):
                    worker = '(' + tag[7:] + ') '
            if timestamp:
                timestr = timestamp.isoformat()
            else:
                timestr = ''
                self._output.write('%s: %s%s [start]\n' %
                                   (timestr, worker, test_id))
            self._emitted.add(test_id)


def cleanup_test_name(name, strip_tags=True, strip_scenarios=False):
    """Clean up the test name for display.

    By default we strip out the tags in the test because they don't help us
    in identifying the test that is run to it's result.

    Make it possible to strip out the testscenarios information (not to
    be confused with tempest scenarios) however that's often needed to
    indentify generated negative tests.
    """
    if strip_tags:
        tags_start = name.find('[')
        tags_end = name.find(']')
        if tags_start > 0 and tags_end > tags_start:
            newname = name[:tags_start]
            newname += name[tags_end + 1:]
            name = newname

    if strip_scenarios:
        tags_start = name.find('(')
        tags_end = name.find(')')
        if tags_start > 0 and tags_end > tags_start:
            newname = name[:tags_start]
            newname += name[tags_end + 1:]
            name = newname

    return name


def get_duration(timestamps):
    start, end = timestamps
    if not start or not end:
        duration = ''
    else:
        delta = end - start
        duration = '%d.%06ds' % (
            delta.days * DAY_SECONDS + delta.seconds, delta.microseconds)
    return duration


def find_worker(test):
    for tag in test['tags']:
        if tag.startswith('worker-'):
            return int(tag[7:])
    return 'NaN'


# Print out stdout/stderr if it exists, always
def print_attachments(stream, test, all_channels=False):
    """Print out subunit attachments.

    Print out subunit attachments that contain content. This
    runs in 2 modes, one for successes where we print out just stdout
    and stderr, and an override that dumps all the attachments.
    """
    channels = ('stdout', 'stderr')
    for name, detail in test['details'].items():
        # NOTE(sdague): the subunit names are a little crazy, and actually
        # are in the form pythonlogging:'' (with the colon and quotes)
        name = name.split(':')[0]
        if detail.content_type.type == 'test':
            detail.content_type.type = 'text'
        if (all_channels or name in channels) and detail.as_text():
            title = "Captured %s:" % name
            stream.write("\n%s\n%s\n" % (title, ('~' * len(title))))
            # indent attachment lines 4 spaces to make them visually
            # offset
            for line in detail.as_text().split('\n'):
                stream.write("    %s\n" % line)


def show_outcome(stream, test):
    global RESULTS
    status = test['status']
    # TODO(sdague): ask lifeless why on this?
    if status == 'exists':
        return

    worker = find_worker(test)
    name = cleanup_test_name(test['id'])
    duration = get_duration(test['timestamps'])

    if worker not in RESULTS:
        RESULTS[worker] = []
    RESULTS[worker].append(test)

    # don't count the end of the return code as a fail
    if name == 'process-returncode':
        return

    if status == 'success':
        stream.write('{%s} %s [%s] ... ok\n' % (
            worker, name, duration))
        print_attachments(stream, test)
    elif status == 'fail':
        FAILS.append(test)
        stream.write('{%s} %s [%s] ... FAILED\n' % (
            worker, name, duration))
        print_attachments(stream, test, all_channels=True)
    elif status == 'skip':
        stream.write('{%s} %s ... SKIPPED: %s\n' % (
            worker, name, test['details']['reason'].as_text()))
    else:
        stream.write('{%s} %s [%s] ... %s\n' % (
            worker, name, duration, test['status']))
        print_attachments(stream, test, all_channels=True)

    stream.flush()


def print_fails(stream):
    """Print summary failure report.

    Currently unused, however there remains debate on inline vs. at end
    reporting, so leave the utility function for later use.
    """
    if not FAILS:
        return
    stream.write("\n==============================\n")
    stream.write("Failed %s tests - output below:" % len(FAILS))
    stream.write("\n==============================\n")
    for f in FAILS:
        stream.write("\n%s\n" % f['id'])
        stream.write("%s\n" % ('-' * len(f['id'])))
        print_attachments(stream, f, all_channels=True)
    stream.write('\n')


def main():
    stream = subunit.ByteStreamToStreamResult(
        sys.stdin, non_subunit_name='stdout')
    starts = Starts(sys.stdout)
    outcomes = testtools.StreamToDict(
        functools.partial(show_outcome, sys.stdout))
    summary = testtools.StreamSummary()
    result = testtools.CopyStreamResult([starts, outcomes, summary])
    result.startTestRun()
    try:
        stream.run(result)
    finally:
        result.stopTestRun()
    return (0 if summary.wasSuccessful() else 1)


if __name__ == '__main__':
    sys.exit(main())
