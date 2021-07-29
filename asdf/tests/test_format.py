import asdf.format

class TestParseAbbreviatedInputs:
    def test_parse_abbreviated_inputs_1(self):
        path, seqid = asdf.format.parse_abbreviated_inputs("36,03107,scratch,iof")
        assert path == '/scratch/cal_wg/flight/products/0036/iof'
        assert seqid == 'ZCAM03107'

    def test_parse_abbreviated_inputs_2(self):
        path, seqid = asdf.format.parse_abbreviated_inputs("36,03107,scratch")
        assert path == '/scratch/cal_wg/flight/products/0036/iof'
        assert seqid == 'ZCAM03107'

    def test_parse_abbreviated_inputs_1(self):
        path, seqid = asdf.format.parse_abbreviated_inputs("36,03107")
        assert path == '/project/m2020/mastcamz/surface/flight/products/0036/iof'
        assert seqid == 'ZCAM03107'

class TestCleanSequenceId:
    def test_clean_sequence_id_1(self):
        assert asdf.format.clean_sequence_id(123) == 'ZCAM00123'

    def test_clean_sequence_id_2(self):
        assert asdf.format.clean_sequence_id("00123") == 'ZCAM00123'

    def test_clean_sequence_id_2(self):
        assert asdf.format.clean_sequence_id("zcam00123") == 'ZCAM00123'
