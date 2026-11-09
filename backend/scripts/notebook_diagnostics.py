"""Reusable, inference-only diagnostic cells for the main training notebook."""
import textwrap


def diagnostic_cells():
    cells = []
    def md(text):
        cells.append(dict(cell_type='markdown', metadata={'tags':['extended_diagnostics']}, source=text))
    def code(text):
        cells.append(dict(cell_type='code', metadata={'tags':['extended_diagnostics']},
                          source=textwrap.dedent(text).strip(), execution_count=None, outputs=[]))
    md('''## Additional graphs and diagnostic matrices
These cells can run independently after a trained model has been exported. They load the existing pipeline, perform inference, and never fit or overwrite it. Test diagnostics describe the already-evaluated holdout; do not tune the model using these plots. Figures are also saved under `backend/reports/emergency_admissions_forecast/figures/extended_diagnostics`.

This is count regression, so correlation and error matrices are more appropriate than a classification confusion matrix. Positive residuals below mean **underprediction** (actual minus predicted).''')
    code('''
    from pathlib import Path
    import json
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import joblib
    from IPython.display import display
    diag_root = next(p for p in [Path.cwd().resolve(), *Path.cwd().resolve().parents]
                     if (p / 'backend/dataset/processed/nhs_england_ae').exists())
    diag_art = diag_root / 'backend/model_artifacts/emergency_admissions_forecast'
    diag_out = diag_root / 'backend/reports/emergency_admissions_forecast/figures/extended_diagnostics'
    diag_out.mkdir(parents=True, exist_ok=True)
    diag_config = json.loads((diag_art / 'forecast_configuration.json').read_text())
    diag_schema = json.loads((diag_art / 'feature_schema.json').read_text())
    diag_data = pd.read_parquet(diag_root / 'backend/dataset/processed/nhs_england_ae/forecasting_features.parquet')
    diag_target = diag_schema['target']
    diag_period = pd.PeriodIndex(diag_data.target_month, freq='M')
    diag_mask = (diag_period >= pd.Period(diag_config['test_target_start'])) & diag_data[diag_target].notna() & diag_data.emergency_admissions_lag_12.notna()
    if diag_config.get('covid_sensitivity_exclusion'):
        diag_mask &= diag_data.covid_disruption_period.eq(0)
    diag_test = diag_data.loc[diag_mask].copy()
    if diag_test.empty:
        raise ValueError('No eligible test rows for diagnostics.')
    diag_model = joblib.load(diag_art / 'healthflow_emergency_admissions_pipeline.joblib')
    diag_test['prediction'] = np.maximum(diag_model.predict(diag_test[diag_schema['features']]), 0)
    diag_test['actual'] = diag_test[diag_target]
    diag_test['residual'] = diag_test.actual - diag_test.prediction
    diag_test['absolute_error'] = diag_test.residual.abs()
    diag_test['target_month'] = diag_test.target_month.astype(str)
    diag_mae = diag_test.absolute_error.mean()
    diag_wape = diag_test.absolute_error.sum() / diag_test.actual.sum()
    diag_saved = json.loads((diag_art / 'test_metrics.json').read_text())
    assert np.isclose(diag_mae, diag_saved['mae'], rtol=1e-6), 'Data/model differ from saved evaluation; review before interpreting.'
    assert np.isclose(diag_wape, diag_saved['wape'], rtol=1e-6)
    print(f'Existing-model holdout: {len(diag_test):,} rows, {diag_test.provider_code.nunique()} providers; '
          f'{diag_test.target_month.min()} to {diag_test.target_month.max()}; MAE {diag_mae:.2f}, WAPE {diag_wape:.2%}')
    plt.rcParams.update({'figure.dpi':110, 'axes.spines.top':False, 'axes.spines.right':False})
    def diag_save(fig, name):
        fig.tight_layout()
        fig.savefig(diag_out / (name + '.png'), dpi=160, bbox_inches='tight')
        plt.show()
        plt.close(fig)
    ''')
    md('''### 1. Training-feature correlation matrix
Pearson correlations use training-period rows only. Strong correlations show redundancy or association, not causation; the target is excluded.''')
    code('''
    diag_cols = ['total_ae_attendances','attendances_under_4_hours','decision_to_admit_waits_over_4_hours',
                 'emergency_admissions_lag_1','emergency_admissions_lag_12',
                 'admissions_rolling_mean_3','admissions_rolling_std_3','admissions_rolling_mean_12']
    diag_train = diag_data.loc[diag_period <= pd.Period(diag_config['training_target_end'])]
    diag_corr = diag_train[diag_cols].corr()
    fig, ax = plt.subplots(figsize=(11,9))
    im = ax.imshow(diag_corr, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(len(diag_cols)), diag_cols, rotation=60, ha='right')
    ax.set_yticks(range(len(diag_cols)), diag_cols)
    for i in range(len(diag_cols)):
        for j in range(len(diag_cols)):
            v = diag_corr.iloc[i,j]
            ax.text(j,i,f'{v:.2f}',ha='center',va='center',color='white' if abs(v)>.65 else 'black')
    ax.set_title('Training-feature correlation matrix')
    fig.colorbar(im, ax=ax, label='Pearson correlation')
    diag_save(fig, '01_feature_correlation_matrix')
    ''')
    md('''### 2. Actual versus predicted and residual diagnostics
The diagonal is perfect prediction. Residual spread and extreme errors reveal weaknesses hidden by an overall score. Each point represents one provider-month.''')
    code('''
    fig, axes = plt.subplots(1,3,figsize=(17,5))
    axes[0].scatter(diag_test.actual,diag_test.prediction,s=9,alpha=.3,color='#177e89')
    diag_limit = max(diag_test.actual.max(),diag_test.prediction.max())
    axes[0].plot([0,diag_limit],[0,diag_limit],'--',color='#b45309')
    axes[0].set(xlabel='Actual admissions',ylabel='Predicted admissions',title='Actual vs predicted')
    axes[1].scatter(diag_test.prediction,diag_test.residual,s=9,alpha=.3,color='#177e89')
    axes[1].axhline(0,color='#b45309',linestyle='--')
    axes[1].set(xlabel='Predicted admissions',ylabel='Actual minus predicted',title='Residuals vs prediction')
    axes[2].hist(diag_test.residual,bins=60,color='#177e89',edgecolor='white')
    axes[2].axvline(0,color='#b45309',linestyle='--')
    axes[2].set(xlabel='Actual minus predicted',ylabel='Provider-month count',title='Residual distribution')
    diag_save(fig,'02_prediction_and_residual_diagnostics')
    ''')
    md('''### 3. Monthly forecast totals and error trend
Totals include only eligible evaluated providers, not all NHS activity. Aggregation can hide cancelling provider-level errors; monthly WAPE sums absolute errors before dividing by admissions.''')
    code('''
    diag_month = diag_test.groupby('target_month')[['actual','prediction','absolute_error']].sum()
    diag_month['wape'] = diag_month.absolute_error.div(diag_month.actual.replace(0,np.nan))*100
    diag_dates = pd.to_datetime(diag_month.index)
    fig, axes = plt.subplots(2,1,figsize=(12,8),sharex=True)
    axes[0].plot(diag_dates,diag_month.actual,label='Actual',marker='o',color='#177e89')
    axes[0].plot(diag_dates,diag_month.prediction,label='Predicted',marker='s',color='#b45309')
    axes[0].set(ylabel='Admissions',title='Monthly totals for evaluated providers'); axes[0].legend()
    axes[1].plot(diag_dates,diag_month.wape,marker='o',color='#177e89')
    axes[1].set(ylabel='WAPE (%)',xlabel='Target month',title='Monthly forecast error')
    diag_save(fig,'03_monthly_forecast_and_error')
    ''')
    md('''### 4. Provider-by-month error matrix
The 15 providers with the highest actual admission totals are selected by volume, not by their error. Red indicates underprediction; blue indicates overprediction. Grey cells mean missing observations. Values are admission counts.''')
    code('''
    diag_top = diag_test.groupby('provider_code').actual.sum().nlargest(15).index
    diag_matrix = diag_test[diag_test.provider_code.isin(diag_top)].pivot_table(index='provider_code',columns='target_month',values='residual',aggfunc='mean').reindex(diag_top)
    fig, ax = plt.subplots(figsize=(15,8))
    diag_cmap = plt.get_cmap('RdBu_r').copy(); diag_cmap.set_bad('#dddddd')
    diag_max = max(float(np.nanmax(np.abs(diag_matrix.to_numpy(dtype=float, na_value=np.nan)))),1)
    im = ax.imshow(np.ma.masked_invalid(diag_matrix.to_numpy(dtype=float, na_value=np.nan)),aspect='auto',cmap=diag_cmap,vmin=-diag_max,vmax=diag_max)
    ax.set_xticks(range(len(diag_matrix.columns)),diag_matrix.columns,rotation=60,ha='right')
    ax.set_yticks(range(len(diag_matrix)),diag_matrix.index)
    ax.set(title='Provider-by-month signed error matrix',xlabel='Target month',ylabel='Provider code')
    fig.colorbar(im,ax=ax,label='Actual minus predicted admissions')
    diag_save(fig,'04_provider_month_error_matrix')
    ''')
    md('''### 5. Validation benchmark comparison and metric matrix
Candidates are compared on validation data, which were used for model selection. Lower MAE, RMSE, and WAPE are better. Matrix colours are scaled separately per metric (0 = best, 1 = worst among candidates); annotations retain original units.''')
    code('''
    diag_bench = pd.read_csv(diag_art / 'benchmark_results.csv').dropna(subset=['wape','mae','rmse']).sort_values('wape')
    diag_bench = diag_bench.set_index('model')
    diag_metric = diag_bench[['mae','rmse','wape']].copy(); diag_metric['wape'] *= 100
    diag_scaled = (diag_metric-diag_metric.min()).div((diag_metric.max()-diag_metric.min()).replace(0,1))
    fig, axes = plt.subplots(1,2,figsize=(14,max(5,len(diag_bench)*.45)))
    axes[0].barh(diag_bench.index,diag_bench.wape*100,color='#177e89'); axes[0].invert_yaxis()
    axes[0].set(xlabel='Validation WAPE (%)',title='Validation benchmark ranking')
    im = axes[1].imshow(diag_scaled,aspect='auto',cmap='YlOrRd',vmin=0,vmax=1)
    axes[1].set_xticks([0,1,2],['MAE','RMSE','WAPE (%)'])
    axes[1].set_yticks(range(len(diag_metric)),diag_metric.index)
    for i in range(len(diag_metric)):
        for j in range(3):
            axes[1].text(j,i,f'{diag_metric.iloc[i,j]:.2f}',ha='center',va='center',color='white' if diag_scaled.iloc[i,j]>.65 else 'black')
    axes[1].set_title('Validation metric matrix')
    fig.colorbar(im,ax=axes[1],label='Within-metric relative error')
    diag_save(fig,'05_benchmark_comparison_matrix')
    ''')
    md('''### 6. Feature importance with variability
Permutation importance is the increase in validation MAE when a feature is shuffled. Error bars show standard deviation across repeats, not confidence intervals. Correlated features can share importance; values are not percentages.''')
    code('''
    diag_importance = pd.read_csv(diag_art / 'feature_importance.csv').nlargest(15,'importance_mean').sort_values('importance_mean')
    fig, ax = plt.subplots(figsize=(12,7))
    ax.barh(diag_importance.feature,diag_importance.importance_mean,xerr=diag_importance.importance_std,color='#177e89',capsize=3)
    ax.axvline(0,color='grey',linewidth=.8)
    ax.set(xlabel='Increase in validation MAE (admissions)',title='Top 15 permutation feature importances')
    diag_save(fig,'06_feature_importance')
    ''')
    md('''### 7. Error by admission volume
Quartiles are descriptive groups based on observed test admissions, not deployable risk categories. WAPE uses the total absolute error divided by total actual admissions within each group.''')
    code('''
    diag_test['volume_group'] = pd.qcut(diag_test.actual,4,duplicates='drop')
    diag_volume = diag_test.groupby('volume_group',observed=True).agg(rows=('actual','size'),actual_total=('actual','sum'),absolute_error=('absolute_error','sum'),mae=('absolute_error','mean'),bias=('residual','mean'))
    diag_volume['wape_pct'] = diag_volume.absolute_error.div(diag_volume.actual_total.replace(0,np.nan))*100
    display(diag_volume)
    fig, axes = plt.subplots(1,2,figsize=(12,5))
    diag_labels = [f'Q{i+1} (n={int(n):,})' for i,n in enumerate(diag_volume.rows)]
    axes[0].bar(diag_labels,diag_volume.mae,color='#177e89'); axes[0].set(ylabel='MAE (admissions)',title='Absolute error by admission volume')
    axes[1].bar(diag_labels,diag_volume.wape_pct,color='#b45309'); axes[1].set(ylabel='WAPE (%)',title='Relative error by admission volume')
    diag_save(fig,'07_volume_group_errors')
    ''')
    return cells
