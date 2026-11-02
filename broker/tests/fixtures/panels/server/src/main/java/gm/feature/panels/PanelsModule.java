package gm.feature.panels;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.PanelBehavior;
import gm.conduit.api.PanelRow;
import gm.conduit.api.PanelView;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.SimpleContainer;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

import java.util.List;

/** Test fixture: says in chat whatever a player does with its panel, so broker/tests/m20_test.py can read what really happened on a real client. */
public final class PanelsModule implements ServerModule {
	private static final int HEAT_TICKS = 200;
	private ServerModuleContext context;

	private void say(String text) {
		this.context.server().getPlayerList().broadcastSystemMessage(Component.literal("PAN " + text), false);
	}

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		context.bindBlock("panel_kiln", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level.getBlockEntity(pos) instanceof SlotBlockEntity machine && player instanceof ServerPlayer serverPlayer) {
					context.openPanel(serverPlayer, "kiln", machine, new Kiln());
				}
				return InteractionResult.SUCCESS;
			}
		});
		context.bindBlock("panel_sieve", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (player instanceof ServerPlayer serverPlayer) {
					context.openPanel(serverPlayer, "sieve", new Sieve(serverPlayer), new PanelBehavior() {});
				}
				return InteractionResult.SUCCESS;
			}
		});
	}

	/** Only remembers what it's shown, and hands it straight back, the way a filter's slot does. */
	private final class Sieve extends SimpleContainer {
		private final ServerPlayer player;

		Sieve(ServerPlayer player) {
			super(1);
			this.player = player;
		}

		@Override
		public int getMaxStackSize() {
			return 1;
		}

		@Override
		public void setItem(int slot, ItemStack stack) {
			if (!stack.isEmpty()) {
				say("remembers " + stack.getItem());
				this.player.getInventory().add(stack.copy());
			}
		}
	}

	private final class Kiln implements PanelBehavior {
		private boolean lit;
		private int heat;
		private boolean told;

		@Override
		public void opened(PanelView panel) {
			panel.setValue("heat", 0);
			panel.setRows("offers", List.of(PanelRow.of("Bread", new ItemStack(Items.BREAD)), new PanelRow("Sold out", ItemStack.EMPTY, false, "Come back tomorrow"), PanelRow.of("Milk")));
		}

		@Override
		public void tick(PanelView panel) {
			if (this.lit) {
				this.heat = Math.min(this.heat + 1, HEAT_TICKS);
				panel.setValue("heat", (float) this.heat / HEAT_TICKS);
			}
			ItemStack held = panel.container().getItem(0);
			if (!this.told && !held.isEmpty()) {
				this.told = true;
				say("holds " + held.getCount() + " " + held.getItem());
			}
		}

		@Override
		public void clicked(PanelView panel, String id, int row, boolean rightClick, boolean shift) {
			say("clicked " + id + " row " + row);
			if (id.equals("start")) {
				this.lit = true;
				panel.setText("state", "Lit");
				panel.setEnabled("start", false);
			}
		}

		@Override
		public void typed(PanelView panel, String id, String value) {
			say("typed " + value);
		}

		@Override
		public void closed(PanelView panel) {
			say("closed");
		}
	}
}
