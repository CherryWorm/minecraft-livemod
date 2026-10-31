package gm.conduit.knowledge;

import com.mojang.brigadier.Command;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.commands.Commands;
import net.minecraft.core.component.DataComponents;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundOpenBookPacket;
import net.minecraft.network.protocol.game.ClientboundSetPlayerInventoryPacket;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.Filterable;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.component.WrittenBookContent;

import java.util.ArrayList;
import java.util.List;

/**
 * A book that holds what a player has learned. It's never a real item: the client is told briefly that it's
 * holding a book, which opens the screen, and is then told the truth. So it can't be dropped, copied or lost,
 * and it needs no client changes.
 */
public final class Codex {
	private static final int PAGE_CHARACTERS = 230;

	private Codex() {}

	public static void register() {
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
				Commands.literal("codex").executes(context -> {
					open(context.getSource().getPlayerOrException());
					return Command.SINGLE_SUCCESS;
				})));
	}

	public static void open(ServerPlayer player) {
		List<KnowledgePlan.Entry> known = Knowledge.instance().knownEntries(player);
		if (known.isEmpty()) {
			player.sendSystemMessage(Component.literal("§7Nothing is written here yet. Look closer at the world."));
			return;
		}
		List<Filterable<Component>> pages = new ArrayList<>();
		for (KnowledgePlan.Entry entry : known) {
			List<String> parts = split(entry.text());
			for (int index = 0; index < parts.size(); index++) {
				String heading = index == 0 ? "§l" + entry.title() + "§r\n\n" : "";
				pages.add(Filterable.passThrough(Component.literal(heading + parts.get(index))));
			}
		}
		ItemStack book = new ItemStack(Items.WRITTEN_BOOK);
		book.set(DataComponents.WRITTEN_BOOK_CONTENT, new WrittenBookContent(Filterable.passThrough("Codex"), "", 0, pages, true));
		int slot = player.getInventory().getSelectedSlot();
		player.connection.send(new ClientboundSetPlayerInventoryPacket(slot, book));
		player.connection.send(new ClientboundOpenBookPacket(InteractionHand.MAIN_HAND));
		player.connection.send(new ClientboundSetPlayerInventoryPacket(slot, player.getInventory().getItem(slot)));
	}

	private static List<String> split(String text) {
		List<String> parts = new ArrayList<>();
		StringBuilder current = new StringBuilder();
		for (String word : text.split(" ")) {
			if (current.length() + word.length() + 1 > PAGE_CHARACTERS && !current.isEmpty()) {
				parts.add(current.toString());
				current.setLength(0);
			}
			if (!current.isEmpty()) {
				current.append(' ');
			}
			current.append(word);
		}
		if (!current.isEmpty()) {
			parts.add(current.toString());
		}
		return parts;
	}
}
