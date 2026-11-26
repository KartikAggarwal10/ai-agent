"""
test_embeddings_flow.py
=======================
Tests for line detection, chunking, embedding generation,
hybrid retrieval (BM25 + FAISS + CrossEncoder), and answer generation.
"""

import sys
from pathlib import Path

# Add python_part to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from embedding_service import is_more_than_20_lines, count_lines, embedding_service

def test_line_counting():
    short_text = "Line 1\nLine 2\nLine 3"
    assert count_lines(short_text) == 3
    assert not is_more_than_20_lines(short_text)

    # 25 lines
    lines = [f"This is line number {i} containing technical notes about project deployment." for i in range(1, 26)]
    long_text = "\n".join(lines)
    assert count_lines(long_text) == 25
    assert is_more_than_20_lines(long_text)
    print("✓ Line counting and threshold detection passed!")

def test_ingest_and_retrieval():
    # 25 lines of realistic text about a hypothetical platform called NovaCloud
    text_data = """
NovaCloud Platform Documentation and Architecture Overview:
Section 1: Introduction
NovaCloud is a distributed compute cloud designed for edge AI workloads.
It features automatic load balancing across 50 regions worldwide.
The system guarantees 99.999% uptime with multi-region failover.
Storage is handled by NovaStore, an object store with sub-10ms latency.
Section 2: Networking and Security
All communications in NovaCloud use TLS 1.3 with mutual authentication.
Zero-trust network architecture is enforced at every gateway.
Firewall rules can be defined using YAML-based security policies.
DDoS protection is provided natively at layer 3, layer 4, and layer 7.
Section 3: Database Engine
NovaDB is the primary database, providing ACID compliance and distributed transactions.
It supports SQL syntax, document collections, and graph traversals.
Backups are taken continuously with point-in-time recovery up to 35 days.
Replication lag is kept under 50 milliseconds across global read replicas.
Section 4: Scaling and Monitoring
Auto-scaling triggers when CPU utilization exceeds 75% for 3 consecutive minutes.
Memory limits can be configured per microservice container.
Prometheus metrics and OpenTelemetry traces are exported by default.
Alerts can be sent to PagerDuty, Slack, and Webhook endpoints.
Section 5: Support and Licensing
NovaCloud is offered under an enterprise subscription with 24/7 engineering support.
Dedicated solution architects assist with migration and performance tuning.
Disaster recovery drills are conducted quarterly.
Contact support@novacloud.internal for onboarding questions.
"""
    assert is_more_than_20_lines(text_data)

    print("[TEST] Running process_pasted_data with query...")
    result = embedding_service.process_pasted_data(
        text=text_data,
        user_query="What is NovaDB and what are its backup capabilities?"
    )

    print("\n--- Result Summary ---")
    print(f"Chunks created: {result['chunk_count']}")
    print(f"Retrieved chunks: {result['retrieved_count']}")
    print(f"Query used: {result['query']}")
    print(f"Answer:\n{result['answer']}")

    assert result["chunk_count"] > 0
    assert result["retrieved_count"] > 0
    assert len(result["answer"]) > 0
    print("\n✓ Embeddings ingestion and hybrid retrieval test passed successfully!")

if __name__ == "__main__":
    print("Testing embeddings flow...")
    test_line_counting()
    test_ingest_and_retrieval()
