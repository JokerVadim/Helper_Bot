import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from telegram.ext import CallbackQueryHandler, CommandHandler, InlineQueryHandler, MessageHandler

import app_handlers
from handlers.callbacks.base import _delete_ok_messages
from shortcuts import SHORTCUTS


class AppHandlersTests(unittest.TestCase):
    def test_register_handlers_adds_commands_messages_and_error_handler(self):
        app = Mock()
        handle_message = Mock()

        app_handlers.register_handlers(app, handle_message)

        registered_commands = set()
        added_callback = False
        added_message_handlers = 0
        added_inline = False
        for call in app.add_handler.call_args_list:
            handler = call[0][0]
            if isinstance(handler, CommandHandler):
                registered_commands.update(handler.commands)
            elif isinstance(handler, CallbackQueryHandler):
                added_callback = True
            elif isinstance(handler, MessageHandler):
                added_message_handlers += 1
            elif isinstance(handler, InlineQueryHandler):
                added_inline = True

        expected = {'start', 'help', 'rub', 'new', 'done', 'cancel', 'status',
                    'export', 't', 'timer', 'al', 'sls', 'shared', 'share',
                    'unshare', 'milk', 'setpin', 'lock', 'allow', 'disallow',
                    'whitelist', 'lockdown', 'logs'}
        expected |= set(SHORTCUTS.keys())

        missing = expected - registered_commands
        self.assertFalse(missing, f"Missing commands: {missing}")

        self.assertTrue(added_callback, "CallbackQueryHandler not registered")
        self.assertGreaterEqual(added_message_handlers, 3, "Not enough MessageHandlers")
        self.assertTrue(added_inline, "Inline handler not registered")
        self.assertEqual(app.add_error_handler.call_count, 1)


class DeleteOkMessagesTests(unittest.TestCase):
    def _run(self, bot, chat_id, *message_ids):
        return asyncio.run(_delete_ok_messages(bot, chat_id, *message_ids))

    def test_single_message_calls_delete_message(self):
        bot = AsyncMock()
        self._run(bot, 1, 42)
        bot.delete_message.assert_called_once_with(chat_id=1, message_id=42)

    def test_single_message_does_not_call_bulk(self):
        bot = AsyncMock()
        self._run(bot, 1, 42)
        bot.delete_messages.assert_not_called()

    def test_multiple_messages_calls_bulk_first(self):
        bot = AsyncMock()
        self._run(bot, 1, 10, 20)
        bot.delete_messages.assert_called_once_with(chat_id=1, message_ids=[10, 20])
        bot.delete_message.assert_not_called()

    def test_bulk_fallback_to_individual(self):
        bot = AsyncMock()
        bot.delete_messages.side_effect = Exception("bulk failed")
        self._run(bot, 1, 10, 20)
        bot.delete_messages.assert_called_once_with(chat_id=1, message_ids=[10, 20])
        self.assertEqual(bot.delete_message.call_count, 2)
        bot.delete_message.assert_any_call(chat_id=1, message_id=10)
        bot.delete_message.assert_any_call(chat_id=1, message_id=20)

    def test_empty_ids_does_nothing(self):
        bot = AsyncMock()
        self._run(bot, 1)
        bot.delete_message.assert_not_called()
        bot.delete_messages.assert_not_called()

    def test_filters_out_zero_ids(self):
        bot = AsyncMock()
        self._run(bot, 1, 0, 42, None)
        bot.delete_message.assert_called_once_with(chat_id=1, message_id=42)
        bot.delete_messages.assert_not_called()

    def test_individual_delete_silent_on_error(self):
        bot = AsyncMock()
        bot.delete_message.side_effect = Exception("chat not found")
        self._run(bot, 1, 42)  # should not raise


if __name__ == "__main__":
    unittest.main()
