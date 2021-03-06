# -*- coding: utf-8 -*-

"""This script converts the curation sheets to BEL."""

import os
import sys

import click

from bel_enrichment import BELSheetsRepository
from pybel import BELGraph
from pybel.cli import echo_warnings_via_pager

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

# Folder pointers
HERE = os.path.abspath(os.path.dirname(__file__))

ROUNDS_DIRECTORY = os.path.abspath(os.path.join(HERE, 'rounds'))
assert os.path.exists(ROUNDS_DIRECTORY)

DATA_DIRECTORY = os.path.abspath(os.path.join(HERE, 'data'))
os.makedirs(DATA_DIRECTORY, exist_ok=True)

graph_metadata = dict(
    name='HBP - INDRA Curation',
    version='0.1.0',
    authors=AUTHOR_STRING,
    contact='charles.hoyt@scai.fraunhofer.de',
)

sheets_repository = BELSheetsRepository(
    directory=ROUNDS_DIRECTORY,
    output_directory=DATA_DIRECTORY,
    metadata=graph_metadata,
)


def get_sheets_graph(use_cached: bool = False, use_tqdm: bool = True) -> BELGraph:
    """Get the BEL graph from all Google sheets.

    .. warning:: this BEL graph isn't pre-filled with namespace and annotation URLs
    """
    return sheets_repository.get_graph(use_cached=use_cached, use_tqdm=use_tqdm)


@click.command()
def main():
    sheets_repository.generate_curation_summary()

    graph = get_sheets_graph()
    graph.summarize()

    if graph.warnings:
        number_errored_documents = len({path for path, _, _ in graph.warnings})
        click.secho(f'Graph had {graph.number_of_warnings()} warnings in {number_errored_documents} documents')
        echo_warnings_via_pager(graph.warnings)
        sys.exit(-1)


if __name__ == '__main__':
    main()
