import unittest

from cores.chatgpt_proxy import api_translator


class ChatGPTProxyTranslatorTest(unittest.TestCase):
    def test_chat_completions_request_translates_to_responses(self):
        body = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a cautious analyst."},
                {"role": "user", "content": "삼성전자 분석 요약"},
            ],
            "max_tokens": 300,
            "reasoning_effort": "low",
        }

        translated = api_translator.translate_request(body)

        self.assertEqual(translated["model"], "gpt-5.4-mini")
        self.assertEqual(translated["instructions"], "You are a cautious analyst.")
        self.assertEqual(translated["input"], [{"role": "user", "content": "삼성전자 분석 요약"}])
        self.assertEqual(translated["max_output_tokens"], 300)
        self.assertEqual(translated["reasoning"], {"effort": "low"})
        self.assertIs(translated["store"], False)
        self.assertIs(translated["stream"], True)

    def test_sse_text_delta_reconstructs_response_output(self):
        sse = "\n".join(
            [
                "event: response.output_text.delta",
                'data: {"delta":"BUY"}',
                "",
                "event: response.completed",
                'data: {"response":{"id":"resp_1","output":[],"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}}',
                "",
            ]
        )

        response = api_translator.collect_sse_to_response(sse)

        self.assertEqual(response["id"], "resp_1")
        self.assertEqual(response["output"][0]["content"][0]["text"], "BUY")


if __name__ == "__main__":
    unittest.main()
