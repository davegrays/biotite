# This source code is part of the Biotite package and is distributed
# under the 3-Clause BSD License. Please see 'LICENSE.rst' for further
# information.

__all__ = ["SubstitutionMatrix"]
__name__ = "biotite.sequence.align"
__author__ = "Patrick Kunzmann"

import functools
from pathlib import Path
import numpy as np
from biotite.sequence.seqtypes import (
    NucleotideSequence,
    PositionalSequence,
    ProteinSequence,
)

# Directory of matrix files
_DB_DIR = Path(__file__).parent / "matrix_data"


class SubstitutionMatrix(object):
    """
    A :class:`SubstitutionMatrix` is the foundation for scoring in
    sequence alignments.
    A :class:`SubstitutionMatrix` maps each possible pairing of a symbol
    of a first alphabet with a symbol of a second alphabet to a score
    (integer).

    The class uses a 2-D (m x n) :class:`ndarray`
    (dtype=:attr:`numpy.int32`),
    where each element stores the score for a symbol pairing, indexed
    by the symbol codes of the respective symbols in an *m*-length
    alphabet 1 and an *n*-length alphabet 2.

    There are 3 ways to creates instances:

    At first a 2-D :class:`ndarray` containing the scores can be
    directly provided.

    Secondly a dictionary can be provided, where the keys are pairing
    tuples and values are the corresponding scores.
    The pairing tuples consist of a symbol of alphabet 1 as first
    element and a symbol of alphabet 2 as second element. Parings have
    to be provided for each possible combination.

    At last a valid matrix name can be given, which is loaded from the
    internal matrix database. The following matrices are avaliable:

        - Nucleotide substitution matrices from NCBI database
            - **NUC** - Also usable with ambiguous alphabet

        - Protein substitution matrices from NCBI database

            - **PAM<n>**
            - **BLOSUM<n>**
            - **MATCH** - Only differentiates between match and mismatch
            - **IDENTITY** - Strongly penalizes mismatches
            - **GONNET** - Not usable with default protein alphabet
            - **DAYHOFF**

        - Corrected protein substitution matrices :footcite:`Hess2016`,
          **<BLOCKS>** is the BLOCKS version, the matrix is based on

            - **BLOSUM<n>_<BLOCKS>**
            - **RBLOSUM<n>_<BLOCKS>**
            - **CorBLOSUM<n>_<BLOCKS>**

        - Structural alphabet substitution matrices

            - **3Di** - For 3Di alphabet from ``foldseek`` :footcite:`VanKempen2024`
            - **PB** - For Protein Blocks alphabet from *PBexplore* :footcite:`Barnoud2017`

    A list of all available matrix names is returned by
    :meth:`list_db()`.

    Since this class can handle two different alphabets, it is possible
    to align two different types of sequences.

    Objects of this class are immutable.

    Parameters
    ----------
    alphabet1 : Alphabet, length=m
        The first alphabet of the substitution matrix.
    alphabet2 : Alphabet, length=n
        The second alphabet of the substitution matrix.
    score_matrix : ndarray, shape=(m,n) or dict or str
        Either a symbol code indexed :class:`ndarray` containing the scores,
        or a dictionary mapping the symbol pairing to scores,
        or a string referencing a matrix in the internal database.

    Attributes
    ----------
    shape : tuple
        The shape of the substitution matrix.

    Raises
    ------
    KeyError
        If the matrix dictionary misses a symbol given in the alphabet.

    References
    ----------

    .. footbibliography::

    Examples
    --------

    Creating a matrix for two different (nonsense) alphabets
    via a matrix dictionary:

    >>> alph1 = Alphabet(["foo","bar"])
    >>> alph2 = Alphabet([1,2,3])
    >>> matrix_dict = {("foo",1):5,  ("foo",2):10, ("foo",3):15,
    ...                ("bar",1):42, ("bar",2):42, ("bar",3):42}
    >>> matrix = SubstitutionMatrix(alph1, alph2, matrix_dict)
    >>> print(matrix.score_matrix())
    [[ 5 10 15]
     [42 42 42]]
    >>> print(matrix.get_score("foo", 2))
    10
    >>> print(matrix.get_score_by_code(0, 1))
    10

    Creating an identity substitution matrix via the score matrix:

    >>> alph = NucleotideSequence.alphabet_unamb
    >>> matrix = SubstitutionMatrix(alph, alph, np.identity(len(alph), dtype=int))
    >>> print(matrix)
        A   C   G   T
    A   1   0   0   0
    C   0   1   0   0
    G   0   0   1   0
    T   0   0   0   1

    Creating a matrix via database name:

    >>> alph = ProteinSequence.alphabet
    >>> matrix = SubstitutionMatrix(alph, alph, "BLOSUM50")
    """

    def __init__(self, alphabet1, alphabet2, score_matrix):
        self._alph1 = alphabet1
        self._alph2 = alphabet2
        if isinstance(score_matrix, dict):
            self._fill_with_matrix_dict(score_matrix)
        elif isinstance(score_matrix, np.ndarray):
            alph_shape = (len(alphabet1), len(alphabet2))
            if score_matrix.shape != alph_shape:
                raise ValueError(
                    f"Matrix has shape {score_matrix.shape}, "
                    f"but {alph_shape} is required"
                )
            if not np.issubdtype(score_matrix.dtype, np.integer):
                raise TypeError("Score matrix must be an integer ndarray")
            self._matrix = score_matrix.astype(np.int32)
            # If the score matrix was converted from a a float matrix,
            # inf values would be converted to 2**31,
            # which is probably undesired and gives overflow issues in the alignment
            # functions
            if (
                np.any(self._matrix == np.iinfo(np.int32).max) or
                np.any(self._matrix == np.iinfo(np.int32).min)
            ):  # fmt: skip
                raise ValueError(
                    "Score values are too large. "
                    "Maybe it was converted from a float matrix containing inf values?"
                )
        elif isinstance(score_matrix, str):
            matrix_dict = SubstitutionMatrix.dict_from_db(score_matrix)
            self._fill_with_matrix_dict(matrix_dict)
        else:
            raise TypeError(
                "Matrix must be either a dictionary, an 2-D ndarray or a string"
            )
        # This class is immutable and has a getter function for the
        # score matrix -> make the score matrix read-only
        self._matrix.setflags(write=False)

    @property
    def shape(self):
        """
        Get the shape (i.e. the length of both alphabets)
        of the substitution matrix.

        Returns
        -------
        shape : tuple
            Matrix shape.
        """
        return (len(self._alph1), len(self._alph2))

    def get_alphabet1(self):
        """
        Get the first alphabet.

        Returns
        -------
        alphabet : Alphabet
            The first alphabet.
        """
        return self._alph1

    def get_alphabet2(self):
        """
        Get the second alphabet.

        Returns
        -------
        alphabet : Alphabet
            The second alphabet.
        """
        return self._alph2

    def score_matrix(self):
        """
        Get the 2-D :class:`ndarray` containing the score values.

        Returns
        -------
        matrix : ndarray, shape=(m,n), dtype=np.int32
            The symbol code indexed score matrix.
            The array is read-only.
        """
        return self._matrix

    def transpose(self):
        """
        Get a copy of this instance, where the alphabets are
        interchanged.

        Returns
        -------
        transposed : SubstitutionMatrix
            The transposed substitution matrix.
        """
        new_alph1 = self._alph2
        new_alph2 = self._alph1
        new_matrix = np.transpose(self._matrix)
        return SubstitutionMatrix(new_alph1, new_alph2, new_matrix)

    def is_symmetric(self):
        """
        Check whether the substitution matrix is symmetric,
        i.e. both alphabets are identical
        and the score matrix is symmetric.

        Returns
        -------
        is_symmetric : bool
            True, if both alphabets are identical and the score matrix
            is symmetric, false otherwise.
        """
        return self._alph1 == self._alph2 and np.array_equal(
            self._matrix, np.transpose(self._matrix)
        )

    def get_score_by_code(self, code1, code2):
        """
        Get the substitution score of two symbols,
        represented by their code.

        Parameters
        ----------
        code1, code2 : int
            Symbol codes of the two symbols to be aligned.

        Returns
        -------
        score : int
            The substitution / alignment score.
        """
        return self._matrix[code1, code2]

    def get_score(self, symbol1, symbol2):
        """
        Get the substitution score of two symbols.

        Parameters
        ----------
        symbol1, symbol2 : object
            Symbols to be aligned.

        Returns
        -------
        score : int
            The substitution / alignment score.
        """
        code1 = self._alph1.encode(symbol1)
        code2 = self._alph2.encode(symbol2)
        return self._matrix[code1, code2]

    def as_positional(self, sequence1, sequence2):
        """
        Transform this substitution matrix and two sequences into positional
        equivalents.

        This means the new substitution matrix is position-specific: It has the lengths
        of the sequences instead of the lengths of their alphabets.
        Its scores represent the same scores as the original matrix, but now mapped
        onto the positions of the sequences.

        Parameters
        ----------
        sequence1, sequence2 : seq.Sequence, length=n
            The sequences to create the positional equivalents from.

        Returns
        -------
        pos_matrix : align.SubstitutionMatrix, shape=(n, n)
            The position-specific substitution matrix.
        pos_sequence1, pos_sequence2 : PositionalSequence, length=n
            The positional sequences.

        Notes
        -----
        After the transformation the substitution scores remain the same, i.e.
        `substitution_matrix.get_score(sequence1[i], sequence2[j])` is equal to
        `pos_matrix.get_score(pos_sequence1[i], pos_sequence2[j])`.

        Examples
        --------

        Run an alignment with the usual substitution matrix:

        >>> seq1 = ProteinSequence("BIQTITE")
        >>> seq2 = ProteinSequence("IQLITE")
        >>> matrix = SubstitutionMatrix.std_protein_matrix()
        >>> print(matrix)
            A   C   D   E   F   G   H   I   K   L   M   N   P   Q   R   S   T   V   W   Y   B   Z   X   *
        A   4   0  -2  -1  -2   0  -2  -1  -1  -1  -1  -2  -1  -1  -1   1   0   0  -3  -2  -2  -1   0  -4
        C   0   9  -3  -4  -2  -3  -3  -1  -3  -1  -1  -3  -3  -3  -3  -1  -1  -1  -2  -2  -3  -3  -2  -4
        D  -2  -3   6   2  -3  -1  -1  -3  -1  -4  -3   1  -1   0  -2   0  -1  -3  -4  -3   4   1  -1  -4
        E  -1  -4   2   5  -3  -2   0  -3   1  -3  -2   0  -1   2   0   0  -1  -2  -3  -2   1   4  -1  -4
        F  -2  -2  -3  -3   6  -3  -1   0  -3   0   0  -3  -4  -3  -3  -2  -2  -1   1   3  -3  -3  -1  -4
        G   0  -3  -1  -2  -3   6  -2  -4  -2  -4  -3   0  -2  -2  -2   0  -2  -3  -2  -3  -1  -2  -1  -4
        H  -2  -3  -1   0  -1  -2   8  -3  -1  -3  -2   1  -2   0   0  -1  -2  -3  -2   2   0   0  -1  -4
        I  -1  -1  -3  -3   0  -4  -3   4  -3   2   1  -3  -3  -3  -3  -2  -1   3  -3  -1  -3  -3  -1  -4
        K  -1  -3  -1   1  -3  -2  -1  -3   5  -2  -1   0  -1   1   2   0  -1  -2  -3  -2   0   1  -1  -4
        L  -1  -1  -4  -3   0  -4  -3   2  -2   4   2  -3  -3  -2  -2  -2  -1   1  -2  -1  -4  -3  -1  -4
        M  -1  -1  -3  -2   0  -3  -2   1  -1   2   5  -2  -2   0  -1  -1  -1   1  -1  -1  -3  -1  -1  -4
        N  -2  -3   1   0  -3   0   1  -3   0  -3  -2   6  -2   0   0   1   0  -3  -4  -2   3   0  -1  -4
        P  -1  -3  -1  -1  -4  -2  -2  -3  -1  -3  -2  -2   7  -1  -2  -1  -1  -2  -4  -3  -2  -1  -2  -4
        Q  -1  -3   0   2  -3  -2   0  -3   1  -2   0   0  -1   5   1   0  -1  -2  -2  -1   0   3  -1  -4
        R  -1  -3  -2   0  -3  -2   0  -3   2  -2  -1   0  -2   1   5  -1  -1  -3  -3  -2  -1   0  -1  -4
        S   1  -1   0   0  -2   0  -1  -2   0  -2  -1   1  -1   0  -1   4   1  -2  -3  -2   0   0   0  -4
        T   0  -1  -1  -1  -2  -2  -2  -1  -1  -1  -1   0  -1  -1  -1   1   5   0  -2  -2  -1  -1   0  -4
        V   0  -1  -3  -2  -1  -3  -3   3  -2   1   1  -3  -2  -2  -3  -2   0   4  -3  -1  -3  -2  -1  -4
        W  -3  -2  -4  -3   1  -2  -2  -3  -3  -2  -1  -4  -4  -2  -3  -3  -2  -3  11   2  -4  -3  -2  -4
        Y  -2  -2  -3  -2   3  -3   2  -1  -2  -1  -1  -2  -3  -1  -2  -2  -2  -1   2   7  -3  -2  -1  -4
        B  -2  -3   4   1  -3  -1   0  -3   0  -4  -3   3  -2   0  -1   0  -1  -3  -4  -3   4   1  -1  -4
        Z  -1  -3   1   4  -3  -2   0  -3   1  -3  -1   0  -1   3   0   0  -1  -2  -3  -2   1   4  -1  -4
        X   0  -2  -1  -1  -1  -1  -1  -1  -1  -1  -1  -1  -2  -1  -1   0   0  -1  -2  -1  -1  -1  -1  -4
        *  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4  -4   1
        >>> alignment = align_optimal(seq1, seq2, matrix, gap_penalty=-10)[0]
        >>> print(alignment)
        BIQTITE
        -IQLITE

        Running the alignment with positional equivalents gives the same result:

        >>> pos_matrix, pos_seq1, pos_seq2 = matrix.as_positional(seq1, seq2)
        >>> print(pos_matrix)
            I   Q   L   I   T   E
        B  -3   0  -4  -3  -1   1
        I   4  -3   2   4  -1  -3
        Q  -3   5  -2  -3  -1   2
        T  -1  -1  -1  -1   5  -1
        I   4  -3   2   4  -1  -3
        T  -1  -1  -1  -1   5  -1
        E  -3   2  -3  -3  -1   5
        >>> pos_alignment = align_optimal(pos_seq1, pos_seq2, pos_matrix, gap_penalty=-10)[0]
        >>> print(pos_alignment)
        BIQTITE
        -IQLITE

        Increase the substitution score for the first symbols in both sequences to align
        to each other:

        >>> score_matrix = pos_matrix.score_matrix().copy()
        >>> score_matrix[0, 0] = 100
        >>> biased_matrix = SubstitutionMatrix(
        ...     pos_matrix.get_alphabet1(), pos_matrix.get_alphabet2(), score_matrix
        ... )
        >>> print(biased_matrix)
            I   Q   L   I   T   E
        B 100   0  -4  -3  -1   1
        I   4  -3   2   4  -1  -3
        Q  -3   5  -2  -3  -1   2
        T  -1  -1  -1  -1   5  -1
        I   4  -3   2   4  -1  -3
        T  -1  -1  -1  -1   5  -1
        E  -3   2  -3  -3  -1   5
        >>> biased_alignment = align_optimal(pos_seq1, pos_seq2, biased_matrix, gap_penalty=-10)[0]
        >>> print(biased_alignment)
        BIQTITE
        I-QLITE
        """
        pos_sequence1 = PositionalSequence(sequence1)
        pos_sequence2 = PositionalSequence(sequence2)

        pos_score_matrix = self._matrix[
            tuple(_cartesian_product(sequence1.code, sequence2.code).T)
        ].reshape(len(sequence1), len(sequence2))
        pos_matrix = SubstitutionMatrix(
            pos_sequence1.get_alphabet(),
            pos_sequence2.get_alphabet(),
            pos_score_matrix,
        )

        return pos_matrix, pos_sequence1, pos_sequence2

    def __repr__(self):
        """Represent SubstitutionMatrix as a string for debugging."""
        return (
            f"SubstitutionMatrix({self._alph1.__repr__()}, {self._alph2.__repr__()}, "
            f"np.{np.array_repr(self._matrix)})"
        )

    def __eq__(self, item):
        if not isinstance(item, SubstitutionMatrix):
            return False
        if self._alph1 != item.get_alphabet1():
            return False
        if self._alph2 != item.get_alphabet2():
            return False
        if not np.array_equal(self.score_matrix(), item.score_matrix()):
            return False
        return True

    def __ne__(self, item):
        return not self == item

    def __str__(self):
        # Create matrix in NCBI format
        string = " "
        for symbol in self._alph2:
            string += f" {str(symbol):>3}"
        string += "\n"
        for i, symbol in enumerate(self._alph1):
            string += f"{str(symbol):>1}"
            for j in range(len(self._alph2)):
                string += f" {int(self._matrix[i, j]):>3d}"
            string += "\n"
        # Remove terminal line break
        string = string[:-1]
        return string

    @staticmethod
    def dict_from_str(string):
        """
        Create a matrix dictionary from a string in NCBI matrix format.

        Symbols of the first alphabet are taken from the left column,
        symbols of the second alphabet are taken from the top row.

        The keys of the dictionary consist of tuples containing the
        aligned symbols and the values are the corresponding scores.

        Parameters
        ----------
        string : str
            The string containing the substitution matrix in NCBI format.

        Returns
        -------
        matrix_dict : dict
            A dictionary representing the substitution matrix.
        """
        lines = [line.strip() for line in string.split("\n")]
        lines = [line for line in lines if len(line) != 0 and line[0] != "#"]
        symbols1 = [line.split()[0] for line in lines[1:]]
        symbols2 = [e for e in lines[0].split()]
        scores = np.array([line.split()[1:] for line in lines[1:]]).astype(int)
        scores = np.transpose(scores)

        matrix_dict = {}
        for i in range(len(symbols1)):
            for j in range(len(symbols2)):
                matrix_dict[(symbols1[i], symbols2[j])] = scores[i, j]
        return matrix_dict

    @staticmethod
    def dict_from_db(matrix_name):
        """
        Create a matrix dictionary from a valid matrix name in the
        internal matrix database.

        The keys of the dictionary consist of tuples containing the
        aligned symbols and the values are the corresponding scores.

        Parameters
        ----------
        matrix_name : str
            The name of the matrix in the internal database.

        Returns
        -------
        matrix_dict : dict
            A dictionary representing the substitution matrix.
        """
        filename = _DB_DIR / f"{matrix_name}.mat"
        with open(filename, "r") as f:
            return SubstitutionMatrix.dict_from_str(f.read())

    @staticmethod
    def list_db():
        """
        List all matrix names in the internal database.

        Returns
        -------
        db_list : list
            List of matrix names in the internal database.
        """
        return [path.stem for path in _DB_DIR.glob("*.mat")]

    @staticmethod
    @functools.cache
    def std_protein_matrix():
        """
        Get the default :class:`SubstitutionMatrix` for protein sequence
        alignments, which is BLOSUM62.

        Returns
        -------
        matrix : SubstitutionMatrix
            Default matrix.
        """
        return SubstitutionMatrix(
            ProteinSequence.alphabet, ProteinSequence.alphabet, "BLOSUM62"
        )

    @staticmethod
    @functools.cache
    def std_nucleotide_matrix():
        """
        Get the default :class:`SubstitutionMatrix` for DNA sequence
        alignments.

        Returns
        -------
        matrix : SubstitutionMatrix
            Default matrix.
        """
        return SubstitutionMatrix(
            NucleotideSequence.alphabet_amb, NucleotideSequence.alphabet_amb, "NUC"
        )

    @staticmethod
    @functools.cache
    def std_3di_matrix():
        """
        Get the default :class:`SubstitutionMatrix` for 3Di sequence
        alignments.
        :footcite:`VanKempen2024`

        Returns
        -------
        matrix : SubstitutionMatrix
            Default matrix.
        """
        # Import inside function to avoid circular import
        from biotite.structure.alphabet.i3d import I3DSequence

        return SubstitutionMatrix(I3DSequence.alphabet, I3DSequence.alphabet, "3Di")

    @staticmethod
    @functools.cache
    def std_protein_blocks_matrix(undefined_match=200, undefined_mismatch=-200):
        """
        Get the default :class:`SubstitutionMatrix` for Protein Blocks sequences.

        The matrix is adapted from *PBxplore* :footcite:`Barnoud2017`.

        Parameters
        ----------
        undefined_match, undefined_mismatch : int, optional
            The match and mismatch score for undefined symbols.
            The default values were chosen arbitrarily, but are in the order of
            magnitude of the other score values.

        Returns
        -------
        matrix : SubstitutionMatrix
            Default matrix.

        References
        ----------

        .. footbibliography::
        """
        from biotite.structure.alphabet.pb import ProteinBlocksSequence

        alphabet = ProteinBlocksSequence.alphabet
        undefined_symbol = ProteinBlocksSequence.undefined_symbol
        matrix_dict = SubstitutionMatrix.dict_from_db("PB")
        # Add match/mismatch scores for undefined symbols residues
        for symbol in alphabet:
            if symbol == undefined_symbol:
                continue
            matrix_dict[symbol, undefined_symbol] = undefined_mismatch
            matrix_dict[undefined_symbol, symbol] = undefined_mismatch
        matrix_dict[undefined_symbol, undefined_symbol] = undefined_match
        return SubstitutionMatrix(
            alphabet,
            alphabet,
            matrix_dict,
        )

    def _fill_with_matrix_dict(self, matrix_dict):
        self._matrix = np.zeros((len(self._alph1), len(self._alph2)), dtype=np.int32)
        for i in range(len(self._alph1)):
            for j in range(len(self._alph2)):
                sym1 = self._alph1.decode(i)
                sym2 = self._alph2.decode(j)
                self._matrix[i, j] = int(matrix_dict[sym1, sym2])


def _cartesian_product(array1, array2):
    """
    Create all combinations of elements from two arrays.
    """
    return np.transpose(
        [
            np.repeat(array1, len(array2)),
            np.tile(array2, len(array1)),
        ]
    )
