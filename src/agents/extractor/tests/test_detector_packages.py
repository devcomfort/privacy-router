from __future__ import annotations


def test_each_backend_package_exposes_its_barrel_api():
    from agents.extractor.lfm import LFMExtractor, LFMParser
    from agents.extractor.llm import LLMExtractor, LLMParser
    from agents.extractor.opf import OPFExtractor, OPFParser
    from agents.extractor.presidio import PresidioExtractor, PresidioParser

    assert LLMExtractor.__module__ == "agents.extractor.llm.extractor"
    assert LLMParser.__module__ == "agents.extractor.llm.parser"
    assert PresidioExtractor.__module__ == "agents.extractor.presidio.extractor"
    assert PresidioParser.__module__ == "agents.extractor.presidio.parser"
    assert OPFExtractor.__module__ == "agents.extractor.opf.extractor"
    assert OPFParser.__module__ == "agents.extractor.opf.parser"
    assert LFMExtractor.__module__ == "agents.extractor.lfm.extractor"
    assert LFMParser.__module__ == "agents.extractor.lfm.parser"
