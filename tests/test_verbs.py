# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2015, 2016 CERN.
#
# Invenio is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# Invenio is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Invenio; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston,
# MA 02111-1307, USA.
#
# In applying this license, CERN does not
# waive the privileges and immunities granted to it by virtue of its status
# as an Intergovernmental Organization or submit itself to any jurisdiction.

"""Test OAI verbs."""

from __future__ import absolute_import

import datetime
import uuid
from copy import deepcopy
from time import sleep

from helpers import run_after_insert_oai_set
from invenio_db import db
from invenio_indexer.api import RecordIndexer
from invenio_pidstore.minters import recid_minter
from invenio_records.api import Record
from lxml import etree

from invenio_oaiserver import current_oaiserver
from invenio_oaiserver.minters import oaiid_minter
from invenio_oaiserver.models import OAISet
from invenio_oaiserver.response import NS_DC, NS_OAIDC, NS_OAIPMH
from invenio_oaiserver.utils import datetime_to_datestamp

NAMESPACES = {'x': NS_OAIPMH, 'y': NS_OAIDC, 'z': NS_DC}


def _xpath_errors(body):
    """Find errors in body."""
    return list(body.iter('{*}error'))


def test_no_verb(app):
    """Test response when no verb is specified."""
    with app.test_client() as c:
        result = c.get('/oai2d')
        tree = etree.fromstring(result.data)
        assert 'Missing data for required field.' in _xpath_errors(
            tree)[0].text


def test_wrong_verb(app):
    """Test wrong verb."""
    with app.test_client() as c:
        result = c.get('/oai2d?verb=Aaa')
        tree = etree.fromstring(result.data)

        assert 'This is not a valid OAI-PMH verb:Aaa' in _xpath_errors(
            tree)[0].text


def test_identify(app):
    """Test Identify verb."""
    FRIENDS = """<friends xmlns="http://www.openarchives.org/OAI/2.0/friends/"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/friends/
        http://www.openarchives.org/OAI/2.0/friends.xsd">
        <baseURL>http://example.org/oai2d</baseURL>
    </friends>"""
    app.config['OAISERVER_DESCRIPTIONS'] = [FRIENDS, FRIENDS]

    with app.test_client() as c:
        result = c.get('/oai2d?verb=Identify')
        assert 200 == result.status_code

        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH', namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:Identify',
                              namespaces=NAMESPACES)) == 1
        repository_name = tree.xpath('/x:OAI-PMH/x:Identify/x:repositoryName',
                                     namespaces=NAMESPACES)
        assert len(repository_name) == 1
        assert repository_name[0].text == 'Invenio-OAIServer'
        base_url = tree.xpath('/x:OAI-PMH/x:Identify/x:baseURL',
                              namespaces=NAMESPACES)
        assert len(base_url) == 1
        assert base_url[0].text == 'http://app/oai2d'
        protocolVersion = tree.xpath('/x:OAI-PMH/x:Identify/x:protocolVersion',
                                     namespaces=NAMESPACES)
        assert len(protocolVersion) == 1
        assert protocolVersion[0].text == '2.0'
        adminEmail = tree.xpath('/x:OAI-PMH/x:Identify/x:adminEmail',
                                namespaces=NAMESPACES)
        assert len(adminEmail) == 1
        assert adminEmail[0].text == 'info@inveniosoftware.org'
        earliestDatestamp = tree.xpath(
            '/x:OAI-PMH/x:Identify/x:earliestDatestamp',
            namespaces=NAMESPACES)
        assert len(earliestDatestamp) == 1
        deletedRecord = tree.xpath('/x:OAI-PMH/x:Identify/x:deletedRecord',
                                   namespaces=NAMESPACES)
        assert len(deletedRecord) == 1
        assert deletedRecord[0].text == 'no'
        granularity = tree.xpath('/x:OAI-PMH/x:Identify/x:granularity',
                                 namespaces=NAMESPACES)
        assert len(granularity) == 1
        description = tree.xpath('/x:OAI-PMH/x:Identify/x:description',
                                 namespaces=NAMESPACES)
        assert len(description) == 2


def test_getrecord(app):
    """Test get record verb."""
    with app.test_request_context():
        pid_value = 'oai:legacy:1'
        with db.session.begin_nested():
            record_id = uuid.uuid4()
            data = {
                '_oai': {'id': pid_value},
                'title_statement': {'title': 'Test0'},
            }
            pid = oaiid_minter(record_id, data)
            record = Record.create(data, id_=record_id)

        db.session.commit()
        assert pid_value == pid.pid_value
        record_updated = record.updated
        with app.test_client() as c:
            result = c.get(
                '/oai2d?verb=GetRecord&identifier={0}&metadataPrefix=oai_dc'
                .format(pid_value))
            assert 200 == result.status_code

            tree = etree.fromstring(result.data)

            assert len(tree.xpath('/x:OAI-PMH', namespaces=NAMESPACES)) == 1
            assert len(tree.xpath('/x:OAI-PMH/x:GetRecord',
                                  namespaces=NAMESPACES)) == 1
            assert len(tree.xpath('/x:OAI-PMH/x:GetRecord/x:record/x:header',
                                  namespaces=NAMESPACES)) == 1
            assert len(tree.xpath(
                '/x:OAI-PMH/x:GetRecord/x:record/x:header/x:identifier',
                namespaces=NAMESPACES)) == 1
            identifier = tree.xpath(
                '/x:OAI-PMH/x:GetRecord/x:record/x:header/x:identifier/text()',
                namespaces=NAMESPACES)
            assert identifier == [pid_value]
            datestamp = tree.xpath(
                '/x:OAI-PMH/x:GetRecord/x:record/x:header/x:datestamp/text()',
                namespaces=NAMESPACES)
            assert datestamp == [datetime_to_datestamp(record_updated)]
            assert len(tree.xpath('/x:OAI-PMH/x:GetRecord/x:record/x:metadata',
                                  namespaces=NAMESPACES)) == 1


def test_getrecord_fail(app):
    """Test GetRecord if record doesn't exist."""
    with app.test_request_context():
        with app.test_client() as c:
            result = c.get(
                '/oai2d?verb=GetRecord&identifier={0}&metadataPrefix=oai_dc'
                .format('not-exist-pid'))
            assert 422 == result.status_code

            tree = etree.fromstring(result.data)

            _check_xml_error(tree, code='idDoesNotExist')


def _check_xml_error(tree, code):
    """Text xml for a error idDoesNotExist."""
    assert len(tree.xpath('/x:OAI-PMH', namespaces=NAMESPACES)) == 1
    error = tree.xpath('/x:OAI-PMH/x:error', namespaces=NAMESPACES)
    assert len(error) == 1
    assert error[0].attrib['code'] == code


def test_identify_with_additional_args(app):
    """Test identify with additional arguments."""
    with app.test_client() as c:
        result = c.get('/oai2d?verb=Identify&notAValidArg=True')
        tree = etree.fromstring(result.data)
        assert 'You have passed too many arguments.' == _xpath_errors(
            tree)[0].text


def test_listmetadataformats(app):
    """Test ListMetadataFormats."""
    _listmetadataformats(app=app, query='/oai2d?verb=ListMetadataFormats')


def test_listmetadataformats_record(app):
    """Test ListMetadataFormats for a record."""
    with app.test_request_context():
        with db.session.begin_nested():
            record_id = uuid.uuid4()
            data = {'title_statement': {'title': 'Test0'}}
            recid_minter(record_id, data)
            pid = oaiid_minter(record_id, data)
            Record.create(data, id_=record_id)
            pid_value = pid.pid_value

        db.session.commit()

    _listmetadataformats(
        app=app,
        query='/oai2d?verb=ListMetadataFormats&identifier={0}'.format(
            pid_value))


def test_listmetadataformats_record_fail(app):
    """Test ListMetadataFormats for a record that doesn't exist."""
    query = '/oai2d?verb=ListMetadataFormats&identifier={0}'.format(
            'pid-not-exixts')
    with app.test_request_context():
        with app.test_client() as c:
            result = c.get(query)

        tree = etree.fromstring(result.data)

        _check_xml_error(tree, code='idDoesNotExist')


def _listmetadataformats(app, query):
    """Try ListMetadataFormats."""
    with app.test_request_context():
        with app.test_client() as c:
            result = c.get(query)

        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH', namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:ListMetadataFormats',
                              namespaces=NAMESPACES)) == 1
        metadataFormats = tree.xpath(
            '/x:OAI-PMH/x:ListMetadataFormats/x:metadataFormat',
            namespaces=NAMESPACES)
        cfg_metadataFormats = deepcopy(
            app.config.get('OAISERVER_METADATA_FORMATS', {}))
        assert len(metadataFormats) == len(cfg_metadataFormats)

        prefixes = tree.xpath(
            '/x:OAI-PMH/x:ListMetadataFormats/x:metadataFormat/'
            'x:metadataPrefix', namespaces=NAMESPACES)
        assert len(prefixes) == len(cfg_metadataFormats)
        assert all(pfx.text in cfg_metadataFormats for pfx in prefixes)

        schemas = tree.xpath(
            '/x:OAI-PMH/x:ListMetadataFormats/x:metadataFormat/'
            'x:schema', namespaces=NAMESPACES)
        assert len(schemas) == len(cfg_metadataFormats)
        assert all(sch.text in cfg_metadataFormats[pfx.text]['schema']
                   for sch, pfx in zip(schemas, prefixes))

        metadataNamespaces = tree.xpath(
            '/x:OAI-PMH/x:ListMetadataFormats/x:metadataFormat/'
            'x:metadataNamespace', namespaces=NAMESPACES)
        assert len(metadataNamespaces) == len(cfg_metadataFormats)
        assert all(nsp.text in cfg_metadataFormats[pfx.text]['namespace']
                   for nsp, pfx in zip(metadataNamespaces, prefixes))


def test_listsets(app):
    """Test ListSets."""
    with app.test_request_context():
        current_oaiserver.unregister_signals_oaiset()
        with db.session.begin_nested():
            a = OAISet(spec='test', name='Test', description='test desc')
            db.session.add(a)

        with app.test_client() as c:
            result = c.get('/oai2d?verb=ListSets')

        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH', namespaces=NAMESPACES)) == 1

        assert len(tree.xpath('/x:OAI-PMH/x:ListSets',
                              namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:ListSets/x:set',
                              namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:ListSets/x:set/x:setSpec',
                              namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:ListSets/x:set/x:setName',
                              namespaces=NAMESPACES)) == 1
        assert len(tree.xpath(
            '/x:OAI-PMH/x:ListSets/x:set/x:setDescription',
            namespaces=NAMESPACES
        )) == 1
        assert len(
            tree.xpath('/x:OAI-PMH/x:ListSets/x:set/x:setDescription/y:dc',
                       namespaces=NAMESPACES)
        ) == 1
        assert len(
            tree.xpath('/x:OAI-PMH/x:ListSets/x:set/x:setDescription/y:dc/'
                       'z:description', namespaces=NAMESPACES)
        ) == 1
        text = tree.xpath(
            '/x:OAI-PMH/x:ListSets/x:set/x:setDescription/y:dc/'
            'z:description/text()', namespaces=NAMESPACES)
        assert len(text) == 1
        assert text[0] == 'test desc'


def test_fail_missing_metadataPrefix(app):
    """Test ListRecords fail missing metadataPrefix."""
    queries = [
        '/oai2d?verb=ListRecords',
        '/oai2d?verb=GetRecord&identifier=123',
        '/oai2d?verb=ListIdentifiers'
    ]
    for query in queries:
        with app.test_request_context():
            with app.test_client() as c:
                result = c.get(query)

            tree = etree.fromstring(result.data)

            _check_xml_error(tree, code='badArgument')


def test_fail_not_exist_metadataPrefix(app):
    """Test ListRecords fail not exist metadataPrefix."""
    queries = [
        '/oai2d?verb=ListRecords&metadataPrefix=not-exist',
        '/oai2d?verb=GetRecord&identifier=123&metadataPrefix=not-exist',
        '/oai2d?verb=ListIdentifiers&metadataPrefix=not-exist'
    ]
    for query in queries:
        with app.test_request_context():
            with app.test_client() as c:
                result = c.get(query)

            tree = etree.fromstring(result.data)

            _check_xml_error(tree, code='badArgument')


def test_listrecords_fail_missing_metadataPrefix(app):
    """Test ListRecords fail missing metadataPrefix."""
    query = '/oai2d?verb=ListRecords&'
    with app.test_request_context():
        with app.test_client() as c:
            result = c.get(query)

        tree = etree.fromstring(result.data)

        _check_xml_error(tree, code='badArgument')


def test_listrecords(app):
    """Test ListRecords."""
    total = 12
    record_ids = []

    with app.test_request_context():
        indexer = RecordIndexer()

        with db.session.begin_nested():
            for idx in range(total):
                record_id = uuid.uuid4()
                data = {'title_statement': {'title': 'Test{0}'.format(idx)}}
                recid_minter(record_id, data)
                oaiid_minter(record_id, data)
                Record.create(data, id_=record_id)
                record_ids.append(record_id)

        db.session.commit()

        for record_id in record_ids:
            indexer.index_by_id(record_id)

        sleep(5)

        with app.test_client() as c:
            result = c.get('/oai2d?verb=ListRecords&metadataPrefix=oai_dc')

        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH', namespaces=NAMESPACES)) == 1

        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords',
                              namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record',
                              namespaces=NAMESPACES)) == 10
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record/x:header',
                              namespaces=NAMESPACES)) == 10
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record/x:header'
                              '/x:identifier', namespaces=NAMESPACES)) == 10
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record/x:header'
                              '/x:datestamp', namespaces=NAMESPACES)) == 10
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record/x:metadata',
                              namespaces=NAMESPACES)) == 10

        resumption_token = tree.xpath(
            '/x:OAI-PMH/x:ListRecords/x:resumptionToken', namespaces=NAMESPACES
        )[0]
        assert resumption_token.text

        with app.test_client() as c:
            result = c.get(
                '/oai2d?verb=ListRecords&resumptionToken={0}'.format(
                    resumption_token.text
                )
            )

        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH', namespaces=NAMESPACES)) == 1

        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords',
                              namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record',
                              namespaces=NAMESPACES)) == 2
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record/x:header',
                              namespaces=NAMESPACES)) == 2
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record/x:header'
                              '/x:identifier', namespaces=NAMESPACES)) == 2
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record/x:header'
                              '/x:datestamp', namespaces=NAMESPACES)) == 2
        assert len(tree.xpath('/x:OAI-PMH/x:ListRecords/x:record/x:metadata',
                              namespaces=NAMESPACES)) == 2

        resumption_token = tree.xpath(
            '/x:OAI-PMH/x:ListRecords/x:resumptionToken', namespaces=NAMESPACES
        )[0]
        assert not resumption_token.text


def test_listidentifiers(app):
    """Test verb ListIdentifiers."""
    from invenio_oaiserver.models import OAISet

    with app.app_context():
        current_oaiserver.unregister_signals_oaiset()
        # create new OAI Set
        with db.session.begin_nested():
            oaiset = OAISet(
                spec='test0',
                name='Test0',
                description='test desc 0',
                search_pattern='title_statement.title:Test0',
            )
            db.session.add(oaiset)
        db.session.commit()

    run_after_insert_oai_set()

    with app.test_request_context():
        indexer = RecordIndexer()

        # create a new record (inside the OAI Set)
        with db.session.begin_nested():
            record_id = uuid.uuid4()
            data = {'title_statement': {'title': 'Test0'}}
            recid_minter(record_id, data)
            pid = oaiid_minter(record_id, data)
            record = Record.create(data, id_=record_id)

        db.session.commit()

        indexer.index_by_id(record_id)
        sleep(2)

        pid_value = pid.pid_value

        # get the list of identifiers
        with app.test_client() as c:
            result = c.get(
                '/oai2d?verb=ListIdentifiers&metadataPrefix=oai_dc'
            )

        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH', namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:ListIdentifiers',
                              namespaces=NAMESPACES)) == 1
        assert len(tree.xpath('/x:OAI-PMH/x:ListIdentifiers/x:header',
                              namespaces=NAMESPACES)) == 1
        identifier = tree.xpath(
            '/x:OAI-PMH/x:ListIdentifiers/x:header/x:identifier',
            namespaces=NAMESPACES
        )
        assert len(identifier) == 1
        assert identifier[0].text == str(pid_value)
        datestamp = tree.xpath(
            '/x:OAI-PMH/x:ListIdentifiers/x:header/x:datestamp',
            namespaces=NAMESPACES
        )
        assert len(datestamp) == 1
        assert datestamp[0].text == datetime_to_datestamp(record.updated)

        # Check from:until range
        with app.test_client() as c:
            result = c.get(
                '/oai2d?verb=ListIdentifiers&metadataPrefix=oai_dc'
                '&from={0}&until={1}&set=test0'.format(
                    datetime_to_datestamp(record.updated - datetime.timedelta(
                        1)),
                    datetime_to_datestamp(record.updated + datetime.timedelta(
                        1)),
                )
            )

        tree = etree.fromstring(result.data)
        identifier = tree.xpath(
            '/x:OAI-PMH/x:ListIdentifiers/x:header/x:identifier',
            namespaces=NAMESPACES
        )
        assert len(identifier) == 1

        # Check that a date without the time will also work
        with app.test_client() as c:
            result = c.get(
                '/oai2d?verb=ListIdentifiers&metadataPrefix=oai_dc'
                '&from={0}&until={1}&set=test0'.format(
                    datetime_to_datestamp(
                        record.updated - datetime.timedelta(1),
                        day_granularity=True),
                    datetime_to_datestamp(
                        record.updated + datetime.timedelta(1),
                        day_granularity=True),
                )
            )

        tree = etree.fromstring(result.data)
        identifier = tree.xpath(
            '/x:OAI-PMH/x:ListIdentifiers/x:header/x:identifier',
            namespaces=NAMESPACES
        )
        assert len(identifier) == 1


def test_list_sets_long(app):
    """Test listing of sets."""
    from invenio_db import db
    from invenio_oaiserver.models import OAISet

    with app.app_context():
        current_oaiserver.unregister_signals_oaiset()
        with db.session.begin_nested():
            for i in range(27):
                oaiset = OAISet(
                    spec='test{0}'.format(i),
                    name='Test{0}'.format(i),
                    description='test desc {0}'.format(i),
                    search_pattern='title_statement.title:Test{0}'.format(i),
                )
                db.session.add(oaiset)
        db.session.commit()

    run_after_insert_oai_set()

    with app.test_client() as c:
        # First page:
        result = c.get('/oai2d?verb=ListSets')
        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH/x:ListSets/x:set',
                              namespaces=NAMESPACES)) == 10

        resumption_token = tree.xpath(
            '/x:OAI-PMH/x:ListSets/x:resumptionToken', namespaces=NAMESPACES
        )[0]
        assert resumption_token.text

        # Second page:
        result = c.get('/oai2d?verb=ListSets&resumptionToken={0}'.format(
            resumption_token.text
        ))
        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH/x:ListSets/x:set',
                              namespaces=NAMESPACES)) == 10

        resumption_token = tree.xpath(
            '/x:OAI-PMH/x:ListSets/x:resumptionToken', namespaces=NAMESPACES
        )[0]
        assert resumption_token.text

        # Third page:
        result = c.get('/oai2d?verb=ListSets&resumptionToken={0}'.format(
            resumption_token.text
        ))
        tree = etree.fromstring(result.data)

        assert len(tree.xpath('/x:OAI-PMH/x:ListSets/x:set',
                              namespaces=NAMESPACES)) == 7

        resumption_token = tree.xpath(
            '/x:OAI-PMH/x:ListSets/x:resumptionToken', namespaces=NAMESPACES
        )[0]
        assert not resumption_token.text


def test_list_sets_with_resumption_token_and_other_args(app):
    """Test list sets with resumption tokens."""
    pass
