# -*- coding: utf-8 -*-
import logging
import time
import contextlib
import discord
from redbot.core import commands
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import box, humanize_number

from .abc import AdventureMixin
from .bank import bank
from .charsheet import Character, has_funds
from .helpers import ConfirmView, escape, smart_embed

_ = Translator("Adventure", __file__)

log = logging.getLogger("red.cogs.adventure")


class RebirthCommands(AdventureMixin):
    @commands.hybrid_command(name="rebirth")
    @commands.bot_has_permissions(add_reactions=True)
    @commands.guild_only()
    async def rebirth(self, ctx: commands.Context):
        """Resets your character level and increases your rebirths by 1."""
        if self.in_adventure(ctx):
            return await smart_embed(
                ctx, _("You tried to rebirth but the monster ahead is commanding your attention."), ephemeral=True
            )
        if not await self.allow_in_dm(ctx):
            return await smart_embed(ctx, _("This command is not available in DM's on this bot."))
        with contextlib.suppress(discord.HTTPException):
            await ctx.defer()
        async with self.get_lock(ctx.author):
            try:
                c = await Character.from_json(ctx, self.config, ctx.author, self._daily_bonus)
            except Exception as exc:
                log.exception("Error with the new character sheet", exc_info=exc)
                return
            if c.lvl < c.maxlevel:
                return await smart_embed(ctx, _("You need to be level `{c.maxlevel}` to rebirth.").format(c=c))
            if not c.last_currency_check + 10 < time.time():
                return await smart_embed(ctx, _("You need to wait a little before rebirthing.").format(c=c))
            if not await bank.is_global():
                rebirth_cost = await self.config.guild(ctx.guild).rebirth_cost()
            else:
                rebirth_cost = await self.config.rebirth_cost()
            base_cost = 1000 * c.rebirths
            current_balance = c.bal
            last_known_currency = c.last_known_currency
            bal = await bank.get_balance(ctx.author)
            withdraw = max(base_cost, int(max((bal - base_cost), 1) * (rebirth_cost / 100.0)))
            currency_name = await bank.get_currency_name(
                ctx.guild,
            )
            if last_known_currency and current_balance / last_known_currency < 0.25:
                currency_name = await bank.get_currency_name(
                    ctx.guild,
                )
                return await smart_embed(
                    ctx,
                    _(
                        "You tried to get rid of all your {currency_name} -- tsk tsk, "
                        "once you get back up to {cur} {currency_name} try again."
                    ).format(
                        currency_name=currency_name,
                        cur=humanize_number(last_known_currency),
                    ),
                )
            else:
                has_fund = await has_funds(ctx.author, withdraw)
            if not has_fund:

                remaining = withdraw - current_balance
                return await smart_embed(
                    ctx,
                    _("You need {remaining} more {currency_name} to be able to rebirth.").format(
                        currency_name=currency_name, remaining=humanize_number(remaining)
                    ),
                )
            space = "\N{EN SPACE}"
            view = ConfirmView(60, ctx.author)
            open_msg = await smart_embed(
                ctx,
                _(
                    "Rebirthing will:\n\n"
                    "* cost {cost} of your {currency}\n"
                    "* cost all of your current gear\n"
                    "{space}- Legendary and Ascended items lose one degradation "
                    "point per rebirth and are broken down when they have 0 left.\n"
                    "{space}- Set items never disappear\n"
                    "* set you back to level 1 while keeping your current class\n\n"
                    "In turn, rebirthing will give you a higher stat base, a better chance "
                    "for acquiring more powerful items, a higher max level, and the "
                    "ability to convert chests to higher rarities after the second rebirth.\n\n"
                    "Would you like to rebirth?"
                ).format(cost=humanize_number(withdraw), space=space * 4, currency=currency_name),
                view=view,
            )
            await view.wait()

            if view.confirmed is None:
                await open_msg.edit(view=None)
                await smart_embed(ctx, "I can't wait forever, you know.")
                return
            if not view.confirmed:
                await open_msg.edit(
                    content=box(
                        _("{c} decided not to rebirth.").format(c=escape(ctx.author.display_name)),
                        lang="ansi",
                    ),
                    embed=None,
                    view=None,
                )
                return

            try:
                c = await Character.from_json(ctx, self.config, ctx.author, self._daily_bonus)
            except Exception as exc:
                log.exception("Error with the new character sheet", exc_info=exc)
                return
            if c.lvl < c.maxlevel:
                await open_msg.edit(
                    content=box(
                        _("You need to be level `{c}` to rebirth.").format(c=c.maxlevel),
                        lang="ansi",
                    ),
                    embed=None,
                    view=None,
                )
                return
            if bal >= withdraw:
                await bank.withdraw_credits(ctx.author, withdraw)
            else:
                await bank.set_balance(ctx.author, 0)

            await open_msg.edit(
                content=box(
                    _("{c}, congratulations on your rebirth.\nYou paid {bal}.").format(
                        c=escape(ctx.author.display_name),
                        bal=humanize_number(withdraw),
                    ),
                    lang="ansi",
                ),
                embed=None,
                view=None,
            )
            await self.config.user(ctx.author).set(await c.rebirth())
