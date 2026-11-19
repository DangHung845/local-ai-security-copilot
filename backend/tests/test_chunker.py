from app.rag.chunker import _split_sections, chunk_markdown


def test_code_block_hash_comment_is_not_heading():
    text = """# Nmap

```bash
# This is a shell comment
nmap -sn 127.0.0.1
```

## Next

Content.
"""

    sections = _split_sections(text)

    assert sections[0][0] == "Nmap"
    assert "# This is a shell comment" in sections[0][1]
    assert sections[1][0] == "Nmap > Next"


def test_tilde_fence_hash_comment_is_not_heading():
    text = """# Host discovery

~~~bash
# comment
nmap -sn 127.0.0.1
~~~
"""

    sections = _split_sections(text)

    assert len(sections) == 1
    assert sections[0][0] == "Host discovery"
    assert "# comment" in sections[0][1]


def test_real_heading_after_code_block_still_works():
    chunks = chunk_markdown("# One\n```text\n# not heading\n```\n## Two\nText", "test.md")

    assert any(chunk.heading == "One" for chunk in chunks)
    assert any(chunk.heading == "One > Two" for chunk in chunks)
