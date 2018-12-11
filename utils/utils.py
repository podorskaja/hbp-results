# -*- coding: utf-8 -*-

"""This script takes the google sheets data and converts it to BEL."""

import logging
import os
from collections import defaultdict
from typing import Dict, Iterable
from typing import Tuple

import pandas as pd
from pybel import BELGraph, from_pickle, to_pickle
from pybel.constants import CITATION_REFERENCE, CITATION_TYPE, CITATION_TYPE_PUBMED
from pybel.parser import BELParser
from tqdm import tqdm

# Curation template columns

NOT_CURATED = 'Not curated'
ERROR = 'Error'
CORRECT = 'Correct'
ERROR_BUT_ALSO_OTHER_STATEMENT = 'Error but other statement was identified'
MODIFIED_BY_CURATOR = 'Modified by curator'

AUTHORS = [
    'Charles Tapley Hoyt',
    'Daniel Domingo-Fernández',
    'Esther Wollert',
    'Sandra Spalek',
    'Keerthika Lohanadan',
    'Rana Al Disi',
    'Lingling Xu',
    'Kristian Kolpeja',
]

AUTHOR_STRING = ', '.join(sorted(AUTHORS, key=lambda s: s.split()[-1]))

ACT_BP_PREFIX = 'act(bp('

# Folder pointers
HERE = os.path.abspath(os.path.dirname(__file__))
DATA_DIRECTORY = os.path.abspath(os.path.join(HERE, os.pardir, 'rounds'))

CACHE_DIRECTORY = os.path.abspath(os.path.join(HERE, os.pardir, 'cache'))
os.makedirs(CACHE_DIRECTORY, exist_ok=True)

SHEETS_BEL_CACHE_PATH = os.path.join(CACHE_DIRECTORY, 'sheets.bel.pickle')

logger = logging.getLogger(__name__)


def _check_curation_template_columns(dataframe, path):
    """Check dataframe columns in curation excel.

    :param pandas.DataFrame dataframe: curation excel template
    :return:
    """
    if 'Curator' not in dataframe.columns:
        logger.warning(f'{path} is missing the "Curator" column')
        return False

    if 'Checked' not in dataframe.columns:
        logger.warning(f'{path} is missing the "Checked" column')
        return False

    if 'Correct' not in dataframe.columns:
        logger.warning(f'{path} is missing the "Correct" column')
        return False

    if 'Changed' not in dataframe.columns:
        logger.warning(f'{path} is missing the "Changed" column')
        return False

    return True


def process_row(bel_parser: BELParser, row: Dict):
    if not row['Checked']:  # don't use unchecked material
        return

    if not (row['Correct'] or row['Changed']):  # if it's neither correct nor changed, then it's fucked
        return

    reference = str(
        row['Citation Reference']
        if 'Citation Reference' in row else
        row['PMID']
    )

    if not reference:
        raise Exception('missing reference')

    bel_parser.control_parser.citation = {
        CITATION_TYPE: CITATION_TYPE_PUBMED,
        CITATION_REFERENCE: reference,
    }
    # Set the evidence
    bel_parser.control_parser.evidence = row['Evidence']
    # TODO set annotations if they exist

    # Set annotations
    bel_parser.control_parser.annotation_dict.update({
        'Curator': {row['Curator']},
        'INDRA_UUID': {row['INDRA UUID']},
        'Confidence': 'Medium',  # needs re-curation
    })

    sub = row['Subject']
    obj = row['Object']

    # Fix ``act(bp`` tags here
    if sub.startswith(ACT_BP_PREFIX):
        sub = sub[len('act('):-1]
    if obj.startswith(ACT_BP_PREFIX):
        obj = obj[len('act('):-1]

    # Build a BEL statement and parse it
    bel = f"{sub} {row['Predicate']} {obj}"

    try:
        bel_parser.parseString(bel)
    except Exception:
        raise Exception(bel)


def get_sheets_graph(use_cached=False) -> BELGraph:
    """Get the BEL graph from all Google sheets.

    Warning: this BEL graph isn't pre-filled with namespace and annotation URLs
    """
    if use_cached and os.path.exists(SHEETS_BEL_CACHE_PATH):
        return from_pickle(SHEETS_BEL_CACHE_PATH)

    graph = BELGraph(
        name='HBP - INDRA Curation',
        version='0.1.0',
        authors=AUTHOR_STRING,
        contact='charles.hoyt@scai.fraunhofer.de',
    )
    logger.info('streamlining parser')
    bel_parser = BELParser(graph)

    for path in tqdm(list(get_enrichment_directories()), desc='Sheets'):
        df = pd.read_excel(path)

        # Check columns in dataframe exist
        if not _check_curation_template_columns(df, path):
            continue

        for line, row in tqdm(df.iterrows(), total=len(df.index), leave=False, desc=path.split('/')[-1].split('_')[0]):
            try:
                process_row(bel_parser, row)
            except Exception as e:
                # logger.info('%s [line %d] - parse error: %s', path, line, e.args[0])
                graph.warnings.append((line, path, e.args[0]))

    to_pickle(graph, SHEETS_BEL_CACHE_PATH)
    return graph


def generate_error_types(path) -> Tuple[dict, str]:
    """Generate report about the types of errors INDRA made.

    :param str path: path to the excel file
    :return: summary of the curation
    """
    df = pd.read_excel(path)

    error_types = defaultdict(int)

    for line, row in df.iterrows():

        if line == 0:
            curator = row.get('Curator')

        error_type = row.get('Error Type')

        if pd.isnull(error_type):
            continue

        # Multiple errors are listed separated by a comma
        for error in str(error_type).split(','):
            # Lower case errors and remove spacing
            error_types[error.lower().strip()] += 1

    return error_types, curator


def generate_curation_report(path) -> dict:
    """Generate report about curated/non-curated statements in a given curation template.

    :param str path: path to the excel file
    :return: summary of the curation
    """
    df = pd.read_excel(path)

    # Check columns in dataframe exist
    if not _check_curation_template_columns(df, path):
        raise ValueError(f'{path} has a problem with the header')

    curation_results = defaultdict(int)

    for line, row in df.iterrows():

        checked = row.get('Checked')
        correct = row.get('Correct')
        changed = row.get('Changed')

        evidence = row.get('Evidence')

        if evidence == 'No evidence text.':
            logger.debug('No evidence text. Skipping...')
            continue

        # Transform real values ('x' and'NaN') to Trues and Falses
        checked = pd.notnull(checked)
        correct = pd.notnull(correct)
        changed = pd.notnull(changed)

        # The statement has not been curated (all 3 columns are empty)
        if not any([checked, correct, changed]):
            curation_results[NOT_CURATED] += 1

        # Only checked is marked
        elif checked and not any([correct, changed]):
            curation_results[ERROR] += 1

        # Correct statements by Indra
        elif correct and not changed:
            curation_results[CORRECT] += 1

        # Statement has been modified by the curator and WAS the original one
        elif checked and changed:
            curation_results[MODIFIED_BY_CURATOR] += 1

        elif changed and correct:
            logger.warning('Conflict in row {}'.format(line))

        # Statement has been modified by the curator but WAS NOT the original one
        elif changed:
            curation_results[ERROR_BUT_ALSO_OTHER_STATEMENT] += 1

        curation_results['Total'] += 1

    return curation_results


def generate_curation_summary():
    """Generate a summary of the curation results on excel."""
    summary_excel_rows = {}
    error_excel_rows = {}

    for path in tqdm(list(get_enrichment_directories()), desc='Generating curation report'):
        gene_symbol = path.split('/')[-2]

        # Subfolder name (Gene Symbol) -> dictionary results
        summary = generate_curation_report(path)

        error_types, curator = generate_error_types(path)

        error_excel_rows[gene_symbol] = error_types

        summary_excel_rows[gene_symbol] = summary

    # Export Summary Report
    df_summary = pd.DataFrame.from_dict(summary_excel_rows, orient='index')
    # Rearrange columns
    df_summary = df_summary[[CORRECT, ERROR, ERROR_BUT_ALSO_OTHER_STATEMENT, MODIFIED_BY_CURATOR, NOT_CURATED, 'Total']]
    df_summary.to_csv(os.path.join(CACHE_DIRECTORY, 'curation_summary.csv'))

    # Export Error Types Report
    df_error = pd.DataFrame.from_dict(error_excel_rows, orient='index')
    df_error.to_csv(os.path.join(CACHE_DIRECTORY, 'error_types.csv'))


def get_enrichment_directories() -> Iterable[str]:
    """List the excel curation sheets."""
    for path in os.listdir(DATA_DIRECTORY):
        folder = os.path.join(DATA_DIRECTORY, path)
        if not (os.path.isdir(folder) and path.startswith('enrichment-')):
            continue
        for subpath in os.listdir(folder):
            subfolder = os.path.join(folder, subpath)
            if not os.path.isdir(subfolder):
                continue
            curated_path = os.path.join(subfolder, f'{subpath}_curated.xlsx')
            if os.path.exists(curated_path):
                yield curated_path


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logger.info('Creating INDRA curation report')
    generate_curation_summary()